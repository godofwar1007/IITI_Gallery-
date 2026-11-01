// Classic script: file:// can load this even when browser ES modules are blocked.
if (location.protocol === 'file:') {
  location.replace(new URL('../../Gallery_Preview.html', location.href).href);
}
