"""Testes isolados: nenhuma conta, rede, publicacao ou Telegram real."""
import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import youtube_api as yt
import youtube_oauth as oauth
import youtube_rotina as routine
import canais_24h as channels
import canais_oficio as oficio


class FakeVault:
    def __init__(self): self.items={}
    def get(self,key): return self.items.get(key)
    def put(self,key,username="",password="",extra=None): self.items[key]={"extra":extra or {}}
    def delete(self,key): return self.items.pop(key,None) is not None


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    vault=FakeVault()
    monkeypatch.setattr(yt,"_vault",lambda:vault)
    import secrets_vault
    monkeypatch.setattr(secrets_vault,"VAULT",vault)
    for name in ("YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setenv(name,"unit-test-only")
    monkeypatch.setattr(yt,"_ACCESS",{"token":"","expira":0,"renovado":0})
    monkeypatch.setattr(yt,"_IDENTITY",{"quando":0,"doc":None})
    monkeypatch.setattr(routine,"STATE",tmp_path/"routine.json")
    monkeypatch.setattr(routine,"ROOT",tmp_path/"pecas")
    monkeypatch.setattr(channels,"DATA",tmp_path)
    monkeypatch.setattr(channels,"ESTADO",tmp_path/"channels.json")
    monkeypatch.setattr(channels,"SESSOES",tmp_path/"sessions.json")
    def forbidden(*a,**kw):raise AssertionError("Nenhuma rede real e permitida neste teste")
    for name in ("get","post","put","request"):
        monkeypatch.setattr(httpx,name,forbidden)
    monkeypatch.setattr(oficio,"informar",forbidden)
    return vault


def resp(code,doc=None,headers=None):
    return httpx.Response(code,json=doc or {},headers=headers)


def test_refresh_automatico_e_cache(monkeypatch):
    calls=[]
    def refresh(*a,**kw):
        calls.append(kw)
        return resp(200,{"access_token":"unit-access","expires_in":3600})
    monkeypatch.setattr(httpx,"post",refresh)
    assert yt.access_token()=="unit-access"
    assert yt.access_token()=="unit-access"
    assert len(calls)==1
    assert calls[0]["data"]["grant_type"]=="refresh_token"
    yt.access_token(force=True)
    assert len(calls)==2


def test_refresh_revogado_nao_usa_cookie(monkeypatch):
    monkeypatch.setattr(httpx,"post",lambda *a,**kw:resp(400,{"error":"invalid_grant","error_description":"private secret never returned"}))
    with pytest.raises(yt.YouTubeError) as e:yt.access_token()
    assert e.value.reason=="invalid_grant"
    assert "private secret" not in str(e.value)
    assert not yt.probe()["ok"]


def test_vault_config_fallback(monkeypatch,isolated):
    for name in ("YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(name)
    assert not yt.configurado()
    isolated.put("youtube_oauth",extra={k:"unit-only" for k in ("YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN")})
    assert yt.configurado()


def test_canal_errado_impede_envio(monkeypatch):
    monkeypatch.setattr(yt,"request",lambda *a,**kw:{"items":[{"id":"wrong-channel"}]})
    with pytest.raises(yt.YouTubeError,match="canal_diferente"):yt.identidade(force=True)


def test_contagem_ausente_nao_e_zero():
    empty=yt.video({"id":"test","statistics":{}})
    zero=yt.video({"id":"test","statistics":{"viewCount":"0","likeCount":"0"}})
    assert empty["views"] is None and empty["likes"] is None
    assert zero["views"]==0 and zero["likes"]==0


def test_pkce_e_state_uso_unico(isolated):
    url=oauth.iniciar()
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert q["access_type"]==["offline"]
    assert q["scope"]==[yt.SCOPE]
    assert q["code_challenge_method"]==["S256"]
    assert oauth._consumir_fluxo("wrong") is None
    state=q["state"][0]
    d=oauth._consumir_fluxo(state)
    assert d["verifier"]
    assert oauth._consumir_fluxo(state) is None


def test_state_expirado(isolated):
    isolated.put(oauth.FLUXO,extra={"state":"unit","verifier":"unit","expira":1})
    assert oauth._consumir_fluxo("unit") is None


def test_callback_sem_state_nao_troca_codigo():
    app=FastAPI();oauth.registrar(app)
    with TestClient(app) as cx:
        r=cx.get('/api/youtube/oauth/callback?code=unit-code-secret&state=wrong')
    assert r.status_code==400
    assert "unit-code-secret" not in r.text


def test_short13_e_video_existente_protegidos(monkeypatch,tmp_path):
    monkeypatch.setattr(yt,"identidade",lambda **kw:{"canal":yt.CHANNEL})
    path=tmp_path/'original.mp4';path.write_bytes(b'x'*10000)
    with pytest.raises(yt.YouTubeError,match="protegido"):
        yt.publicar(path,{"id":"h6Y-M4AgX6s"},'a'*16)


def test_upload_confirmado_nao_inicia_segunda_vez(monkeypatch,tmp_path,isolated):
    monkeypatch.setattr(yt,"identidade",lambda **kw:{"canal":yt.CHANNEL})
    monkeypatch.setattr(yt,"access_token",lambda **kw:"unit-only")
    calls=[]
    class Client:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**k):
            calls.append('post');return resp(200,headers={"Location":"https://www.googleapis.com/unit-upload"})
        def put(self,*a,**k):
            calls.append('put')
            if not k.get('content'):return resp(308)
            return resp(201,{"id":"new-video","status":{"privacyStatus":"public"}})
    monkeypatch.setattr(httpx,"Client",Client)
    path=tmp_path/'original.mp4';path.write_bytes(b'x'*10000)
    assert yt.publicar(path,{},'b'*16)['id']=='new-video'
    assert yt.publicar(path,{},'b'*16)['id']=='new-video'
    assert calls.count('post')==1
    assert isolated.get('youtube_upload_'+'b'*16)['extra']['video']=='new-video'
    assert 'url' not in isolated.get('youtube_upload_'+'b'*16)['extra']


def test_resposta_so_a_comentario_real(monkeypatch):
    monkeypatch.setattr(yt,"identidade",lambda **kw:{"canal":yt.CHANNEL})
    with pytest.raises(yt.YouTubeError,match='sem_comentario_real'):
        yt.responder('invented','texto',{})
    observed={"id":"real","pode_responder":True,"autor":"viewer","respondeu_dono":False}
    with pytest.raises(yt.YouTubeError,match='inadequada'):
        yt.responder('real','https://spam.invalid',observed)
    monkeypatch.setattr(yt,"request",lambda *a,**kw:{"id":"reply-id"})
    assert yt.responder('real','Obrigado por assistir.',observed)=='reply-id'


def test_cookies_nao_chamam_studio_ou_arena(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Nao chamar Studio ou Arena')
    monkeypatch.setattr(channels,'_youtube',forbidden)
    monkeypatch.setattr(channels,'_arena',forbidden)
    monkeypatch.setattr(channels,'_sessoes',lambda:{})
    monkeypatch.setattr(channels,'_bilibili_nav',lambda *a:{'ok':True})
    monkeypatch.setattr(channels,'_tiktok',lambda *a:('ok','',{}))
    monkeypatch.setattr(yt,'probe',lambda:{'ok':True,'renovado_em':123})
    channels.ciclo_cookies()
    assert channels._estado()['cookies']['youtube_modo']=='oauth_oficial'


def healthy_doc():
    now=int(time.time())
    return {'cookies':{'youtube':'ok','bilibili':'ok','tiktok':'ok'},
        'youtube':{'ok':True,'views':0,'quando':now},'bilibili':{'views':0,'quando':now},
        'tiktok':{'seguidores':1,'curtidas':1,'videos':1,'quando':now,'views_por_video':{'unit':0}},
        'agentes':{a:{'quando':now,'ultimo':'unit','saude':'ok'} for a in channels.AGENTES}}


def test_nao_da_all_clear_so_por_ter_env():
    d=healthy_doc();d['youtube']['views']=None
    assert not oficio.em_ordem(d)[0]
    d=healthy_doc();d['agentes'].pop('youtube-cria')
    assert not oficio.em_ordem(d)[0]
    d=healthy_doc();d['tiktok'].pop('views_por_video')
    assert not oficio.em_ordem(d)[0]
    assert oficio.em_ordem(healthy_doc())[0]


def test_telegram_diz_verdade_e_nao_inventa_contagens():
    text=oficio.texto_telegram('unit',False,'unit',{})
    assert 'chat da Arena nao foi aberto' in text
    assert 'views nao lido' in text
    assert 'Esta tudo em ordem: nao' in text


def test_autor_nao_publica_sem_oauth(monkeypatch):
    monkeypatch.setattr(yt,'probe',lambda:{'ok':False,'motivo':'oauth_ausente'})
    msg,fields=routine.cria()
    assert fields['saude']=='falha'
    assert 'nao publico' in msg


def test_privado_nao_e_publico_e_nao_apaga(monkeypatch,tmp_path):
    folder=routine.ROOT/('c'*16);folder.mkdir(parents=True);(folder/'original.mp4').write_bytes(b'unit')
    job={'id':'c'*16,'video':'new-video','estado':'aceito','peca':{'titulo':'unit'}}
    d={'jobs':[job]}
    monkeypatch.setattr(yt,'videos',lambda ids:[{'privacidade':'private','upload_status':'processed','processamento':'succeeded'}])
    msg,fields=routine._confirm(job,d)
    assert fields['saude']=='falha'
    assert (folder/'original.mp4').exists()
    assert job['estado']=='aceito_nao_publico'


def test_publico_processado_apaga_so_apos_confirmar(monkeypatch):
    folder=routine.ROOT/('d'*16);folder.mkdir(parents=True);(folder/'original.mp4').write_bytes(b'unit')
    job={'id':'d'*16,'video':'new-video','estado':'aceito','peca':{'titulo':'unit'}}
    d={'jobs':[job]}
    monkeypatch.setattr(yt,'videos',lambda ids:[{'privacidade':'public','upload_status':'processed','processamento':'succeeded','publicado_em':'2026-10-08T00:00:00Z'}])
    msg,fields=routine._confirm(job,d)
    assert fields['saude']=='ok' and not folder.exists()
    assert job['copia_apagada'] is True


def test_julga_so_depois_de_24h():
    assert 'ainda nao fez 24h' in oficio.juizo(100,0,100+86399)
    assert 'gerou view nao' in oficio.juizo(100,0,100+86400)
    assert 'sem view lida' in oficio.juizo(100,None,100+86400)


def test_titulo_copiado_e_recusado(monkeypatch):
    data={'titulo':'Título copiado','descricao':'ficcao','fala':'Uma historia com palavras originais. '*10}
    monkeypatch.setattr(routine,'_llm',lambda *a:json.dumps(data,ensure_ascii=False))
    with pytest.raises(yt.YouTubeError,match='titulo_repetido'):
        routine.planejar({'amostras':[{'titulo':'Título copiado'}]},set())


def test_link_curto_preserva_pkce_sem_abertura_arbitraria():
    url=oauth.iniciar()
    state=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['state'][0]
    app=FastAPI();oauth.registrar(app)
    with TestClient(app) as cx:
        r=cx.get('/api/youtube/oauth/callback?iniciar='+state,follow_redirects=False)
        denied=cx.get('/api/youtube/oauth/callback?iniciar=wrong',follow_redirects=False)
    assert r.status_code==302
    assert r.headers['location']==url
    assert denied.status_code==400
