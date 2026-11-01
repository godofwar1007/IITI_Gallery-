"""Verify sessions and gallery state survive a non-overlapping deployment restart."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import httpx


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url',required=True)
    p.add_argument('--organizer-file',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('integration-checks/modal-restart.json'))
    args=p.parse_args()
    creds=json.loads(args.organizer_file.read_text(encoding='utf-8'))
    with httpx.Client(base_url=args.url,timeout=180,follow_redirects=True,max_redirects=2) as client:
        client.post('/api/v1/auth/login',json={'password':creds['GALLERY_ADMIN_PASSWORD']}).raise_for_status()
        before=client.get('/api/v1/admin/status').json()
        photos_before=client.get('/api/v1/gallery?limit=120').json()
        # A no-change deploy is skipped by Modal, so explicitly stop this app first.
        subprocess.run([sys.executable,'-m','modal','app','stop','iiti-fieldnotes-gallery','--yes'],check=True)
        subprocess.run([sys.executable,'-m','modal','deploy','backend/deploy/modal_app.py','--strategy','recreate'],check=True)
        ready=client.get('/health/ready');ready.raise_for_status();assert ready.json()['ready']
        # Reuse the original cookie without signing in again: its database row must persist.
        response=client.get('/api/v1/admin/status');response.raise_for_status();after=response.json()
        photos_after=client.get('/api/v1/gallery?limit=120').json()
        assert before['instance_id']!=after['instance_id']
        assert before['collections']==after['collections'] and after['total']==252
        assert [(x['id'],x['created']) for x in photos_before['items']]==[(x['id'],x['created']) for x in photos_after['items']]
        report={'passed':True,'session_survived':True,'gallery_timestamps_survived':True,
                'before_instance':before['instance_id'],'after_instance':after['instance_id'],
                'collections':after['collections'],'gpu_name':after['gpu_name']}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
