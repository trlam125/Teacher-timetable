import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from test_auth_security import request
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from app.services.authentication import csrf


class RequestSecurityTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI(dependencies=[Depends(csrf.verify_request_csrf)])
        @app.get('/token')
        def token(req: Request):
            nonce, value = csrf.form_token(req)
            response = JSONResponse({'token': value})
            response.set_cookie(csrf.CSRF_COOKIE, nonce, secure=True, httponly=True)
            return response
        @app.post('/json')
        def mutate_json(payload: dict):
            return {'ok': True}
        @app.post('/form')
        def mutate_form(name: str = Form(...)):
            return {'name': name}
        @app.post('/upload')
        async def upload(file: UploadFile = File(...)):
            return {'size': len(await file.read())}
        @app.websocket('/ws')
        async def socket(ws: WebSocket):
            await ws.accept()
            await ws.send_text('ready')
            await ws.close()
        self.client = TestClient(app, base_url='https://testserver')
        self.token = self.client.get('/token').json()['token']

    def tearDown(self):
        self.client.close()

    def test_json_mutations_require_header_and_reject_foreign_origin(self):
        self.assertEqual(self.client.post('/json', json={}).status_code, 403)
        headers = {'X-CSRF-Token': self.token, 'Origin': 'https://testserver'}
        self.assertEqual(self.client.post('/json', json={}, headers=headers).status_code, 200)
        headers['Origin'] = 'https://attacker.invalid'
        self.assertEqual(self.client.post('/json', json={}, headers=headers).status_code, 403)

    def test_native_forms_and_multipart_preserve_body(self):
        response = self.client.post('/form', data={'name': 'An', 'csrf_token': self.token})
        self.assertEqual(response.json(), {'name': 'An'})
        response = self.client.post('/upload', data={'csrf_token': self.token}, files={'file': ('test.txt', b'abc')})
        self.assertEqual(response.json(), {'size': 3})

    def test_global_http_dependency_does_not_break_websocket_injection(self):
        with self.client.websocket_connect('/ws') as socket:
            self.assertEqual(socket.receive_text(), 'ready')


class BroadcastSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_broadcast_checks_session_after_acquiring_send_lock(self):
        from app.services.realtime import manager as module
        manager = module.RealtimeConnectionManager()
        socket = AsyncMock()
        waiting = asyncio.Event()
        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                waiting.set()
                return await super().acquire()
        send_lock = ObservedLock()
        await send_lock.acquire()
        waiting.clear()
        manager._connections[1]['test'] = socket
        manager._send_locks['test'] = send_lock
        with patch.object(module, 'websocket_session_user', return_value=None) as validate, \
             patch.object(manager, 'remove', return_value=False):
            task = asyncio.create_task(manager._broadcast_local({'private': 'message'}))
            await asyncio.wait_for(waiting.wait(), 2)
            validate.assert_not_called()
            send_lock.release()
            await asyncio.wait_for(task, 2)
            socket.send_json.assert_not_called()
            socket.close.assert_awaited_once_with(code=4401)


if __name__ == '__main__':
    unittest.main()
