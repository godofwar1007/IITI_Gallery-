import time
import uuid


async def test_ready_review_not_starved_by_new_unprocessed_uploads(bundle):
    service,_,admin,_,_=bundle
    old_ids=[]
    def populate(db):
        for i in range(160):
            uid=uuid.uuid4().hex
            state='validated' if i<10 else 'validating'
            if i<10:old_ids.append(uid)
            db.execute('INSERT INTO uploads(id,owner,client_key,expected,mime,state,review,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (uid,'test',uid,100,'image/jpeg',state,'pending',time.time()+i,time.time()))
    await service.store.call(populate,True)
    rows=(await admin.get('/api/v1/admin/review?filter=pending&limit=20')).json()['items']
    assert [r['id'] for r in rows[:10]]==old_ids
    assert all(r['state']=='validated' for r in rows[:10])


async def test_pending_filter_happens_before_page_limit(bundle):
    service,_,admin,_,_=bundle
    target=uuid.uuid4().hex
    def populate(db):
        for i in range(1010):
            uid=target if i==1009 else uuid.uuid4().hex
            db.execute('INSERT INTO uploads(id,owner,client_key,expected,mime,state,review,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (uid,'test',uid,100,'image/jpeg','validating','pending' if i==1009 else 'approved',time.time()+i,time.time()))
    await service.store.call(populate,True)
    rows=(await admin.get('/api/v1/admin/review?filter=pending&limit=20')).json()['items']
    assert len(rows)==1 and rows[0]['id']==target
