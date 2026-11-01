"""Allow the exact published frontend origin; keeps organizer credentials unchanged."""
import argparse
from urllib.parse import urlparse
import modal


def main():
    p=argparse.ArgumentParser()
    p.add_argument('url',help='Exact HTTPS origin of the Vercel site, not a preview wildcard')
    args=p.parse_args()
    parsed=urlparse(args.url)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {'','/'}):
        p.error('Supply an HTTPS origin without credentials, path, query or fragment')
    origin=args.url.rstrip('/')
    modal.Secret.from_name('iiti-gallery-runtime-v1').update({'GALLERY_PUBLIC_URL':origin})
    print('Allowed frontend origin saved. Stop the app and redeploy with --strategy recreate to load it; unchanged deployments may be skipped.')


if __name__=='__main__': main()
