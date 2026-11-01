import httpx


async def test_open_gallery_search_media_and_profile_without_login(bundle):
    service,_,_,_,app=bundle
    service.config.public_gallery=True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as visitor:
        status=await visitor.get('/api/v1/admin/status')
        assert status.status_code==200 and not status.json()['organizer']
        assert status.json()['public_gallery']
        gallery=await visitor.get('/api/v1/gallery')
        assert gallery.status_code==200 and gallery.json()['total']==120
        assert (await visitor.get(gallery.json()['items'][0]['image'])).status_code==200
        assert (await visitor.post('/api/v1/search/text',json={'query':'a dog'})).status_code==200
        assert (await visitor.post('/api/v1/admin/text-profile',json={'text_profile':'base'})).status_code==200
        for path in ['/api/v1/admin/review','/api/v1/admin/media/not-an-asset']:
            assert (await visitor.get(path)).status_code==401
        for path,body in [('/api/v1/admin/finish',{'confirm':'DELETE STUDENT PHOTOS'}),
                          ('/api/v1/admin/event',{'intake':'closed'}),
                          ('/api/v1/admin/assets/not-an-asset/hide',{})]:
            assert (await visitor.post(path,json=body)).status_code==401
        assert (await visitor.post('/api/v1/demo/photos',content=b'not-a-photo')).status_code==401
