"""Strict local-only runtime plus one serialized model lane."""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import nullcontext
from .profiles import DEFAULT_ADAPTER, PROFILES, validate_adapter
import numpy as np
from PIL import Image

from .config import MODEL_ID, REVISION


class LocalEncoder:
    def __init__(self, snapshot: Path, processor: Path, profile="campus-run2", adapter=None):
        self.supports_profiles = True
        self.profile = "base"
        self.adapter_path = Path(adapter or DEFAULT_ADAPTER)
        self.adapter_loaded = False
        if profile == "campus-run2": validate_adapter(self.adapter_path)
        import os
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
        import torch
        from transformers import AutoModel, AutoProcessor
        if not snapshot or (snapshot / 'REVISION').read_text().strip() != REVISION:
            raise ValueError('Model snapshot REVISION does not match the seed')
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.processor = AutoProcessor.from_pretrained(processor, local_files_only=True)
        self.model = AutoModel.from_pretrained(snapshot, local_files_only=True, dtype=self.dtype,
                                              attn_implementation='sdpa').to(self.device).eval()
        self.max_length = 64
        if self.model.config.text_config.max_position_embeddings != 64:
            raise ValueError("Unexpected text context length")
        self.set_profile(profile)
        if self.text(['a photo']).shape != (1, 1536):
            raise ValueError('Model feature dimension mismatch')

    def normalize(self, output):
        t = self.torch
        if not t.is_tensor(output):
            output = output.pooler_output
        value = t.nn.functional.normalize(output.float(), dim=-1).cpu().numpy()
        if value.ndim != 2 or value.shape[1] != 1536 or not np.isfinite(value).all() or not np.allclose(np.linalg.norm(value, axis=1), 1, atol=1e-4):
            raise ValueError('Invalid model features')
        return value

    def set_profile(self, profile):
        if profile not in PROFILES: raise ValueError('Unknown text profile')
        if profile == 'campus-run2' and not self.adapter_loaded:
            validate_adapter(self.adapter_path)
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, self.adapter_path, is_trainable=False).eval()
            names = [name for name, _ in self.model.named_parameters() if 'lora_' in name]
            if not names or any('text_model' not in name or 'vision_model' in name for name in names):
                raise ValueError('Unsafe adapter: LoRA parameters outside text tower')
            self.adapter_loaded = True
        self.profile = profile

    def text(self, texts, profile=None):
        inputs = self.processor(text=[s.lower().strip() for s in texts], padding='max_length',
                                max_length=self.max_length, truncation=True, return_tensors='pt')
        profile = profile or self.profile
        if profile not in PROFILES or (profile == 'campus-run2' and not self.adapter_loaded):
            raise ValueError('Text profile unavailable')
        context = self.model.disable_adapter() if self.adapter_loaded and profile == 'base' else nullcontext()
        with self.torch.inference_mode(), context:
            return self.normalize(self.model.get_text_features(**{k:v.to(self.device) for k,v in inputs.items()}))

    def images(self, paths):
        images = []
        for p in paths:
            with Image.open(p) as im:
                images.append(im.convert('RGB'))
        inputs = self.processor(images=images, return_tensors='pt')
        inputs = {k:v.to(device=self.device, dtype=self.dtype if v.is_floating_point() else v.dtype) for k,v in inputs.items()}
        context = self.model.disable_adapter() if self.adapter_loaded else nullcontext()
        with self.torch.inference_mode(), context:
            return self.normalize(self.model.get_image_features(**inputs))


class Broker:
    def __init__(self, encoder):
        self.encoder = encoder
        self.query = deque()
        self.images = deque()
        self.wake = asyncio.Event()
        self.executor = ThreadPoolExecutor(1, thread_name_prefix='inference')
        self.closed = False
        self.error = None
        self.task = None

    async def submit(self, function, *, background=False):
        lane = self.images if background else self.query
        if len(lane) >= (1200 if background else 8):
            raise RuntimeError('inference_busy')
        future = asyncio.get_running_loop().create_future()
        lane.append((function, future))
        self.wake.set()
        return await future

    async def run(self):
        streak = 0
        while not self.closed:
            if not self.query and not self.images:
                self.wake.clear()
                await self.wake.wait()
                continue
            lane = self.query if self.query and (streak < 4 or not self.images) else self.images
            function, future = lane.popleft()
            if future.cancelled():
                continue
            streak = streak + 1 if lane is self.query else 0
            try:
                result = await asyncio.get_running_loop().run_in_executor(self.executor, function)
                self.error = None
                if not future.done():
                    future.set_result(result)
            except Exception as error:
                self.error = type(error).__name__
                if not future.done():
                    future.set_exception(error)

    async def close(self):
        self.closed = True
        self.wake.set()
        if self.task:
            await self.task
        for _, future in [*self.query, *self.images]:
            if not future.done():
                future.cancel()
        self.executor.shutdown(wait=True)
