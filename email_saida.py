"""Saída de e-mail sem a porta que o Render grátis fecha.

O Hermes só sabe IMAP/SMTP e entra no SMTP com a senha do Gmail. Daqui a
porta 587 não abre. Então o Hermes fala com um SMTP local, em 127.0.0.1.
Quem entrega de verdade é a API do Brevo, na 443. Se o Brevo falhar e o PC
do dono estiver ligado com a mão nova, a resposta sai pela internet de casa.
"""
from __future__ import annotations

import base64
import os
import re
import socket
import ssl
import threading
from email.parser import Parser
from pathlib import Path

HOME = Path(os.environ.get("ORBE_HERMES_HOME", "data/hermes")).resolve()
PORTA = 1587
HOST = "127.0.0.1"
_CHAVE = HOME / "saida.key"
_LOGIN = HOME / "saida.login"
_CERT = HOME / "saida"
_trava = threading.Lock()
_servidor: socket.socket | None = None
_fila_pc: list[dict] = []
_pc_capaz = False

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def tem_chave() -> bool:
    return bool(_ler_chave())


def tem_login() -> bool:
    return bool(_ler_login())


def eh_smtp() -> bool:
    return _ler_chave().lower().startswith("xsmtpsib-")


def pronta() -> bool:
    if not tem_chave():
        return False
    if eh_smtp():
        return tem_login() and smtp_aceito()
    return remetente_confirmado()


def _ler_chave() -> str:
    try:
        return _CHAVE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def senha_gmail() -> str:
    envp = HOME / ".env"
    try:
        for linha in envp.read_text(encoding="utf-8").splitlines():
            if linha.startswith("EMAIL_PASSWORD="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def _gmail() -> str:
    envp = HOME / ".env"
    try:
        for linha in envp.read_text(encoding="utf-8").splitlines():
            if linha.startswith("EMAIL_ADDRESS="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _ler_login() -> str:
    try:
        return _LOGIN.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def salvar_login(valor: str) -> str:
    valor = (valor or "").strip()
    if "@" not in valor or any(c.isspace() for c in valor) or len(valor) > 120:
        return "o login não é o que aparece em Suas configurações SMTP"
    HOME.mkdir(parents=True, exist_ok=True)
    _LOGIN.write_text(valor + "\n", encoding="utf-8")
    try:
        os.chmod(_LOGIN, 0o600)
    except Exception:
        pass
    global _smtp_ate
    _smtp_ate = 0.0
    return ""


def salvar_chave(valor: str) -> str:
    """Grava a chave. Devolve o erro, ou vazio se aceitou."""
    valor = (valor or "").strip()
    if len(valor) < 20 or any(c.isspace() for c in valor):
        return "a chave não veio inteira"
    if not valor.lower().startswith("xsmtpsib-"):
        erro = _brevo_ok(valor)
        if erro:
            return erro
    HOME.mkdir(parents=True, exist_ok=True)
    _CHAVE.write_text(valor + "\n", encoding="utf-8")
    try:
        os.chmod(_CHAVE, 0o600)
    except Exception:
        pass
    global _smtp_ate
    _smtp_ate = 0.0
    try:
        import state_backup
        state_backup.sujo()
    except Exception:
        pass
    return ""


def _brevo_ok(chave: str) -> str:
    import json
    import urllib.request

    req = urllib.request.Request(
        "https://api.brevo.com/v3/account",
        headers={"api-key": chave, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except Exception as exc:
        codigo = getattr(exc, "code", None)
        if codigo in {401, 403}:
            return "o Brevo não aceitou essa chave"
        return "não consegui falar com o Brevo agora"
    return ""


_smtp_ate = 0.0
_smtp_ok = False


def smtp_aceito(forcar: bool = False) -> bool:
    global _smtp_ate, _smtp_ok
    import time

    if not forcar and time.time() < _smtp_ate:
        return _smtp_ok
    ok = False
    chave, login = _ler_chave(), _ler_login()
    if chave and login:
        import smtplib

        try:
            with smtplib.SMTP("smtp-relay.brevo.com", 2525, timeout=20) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(login, chave)
            ok = True
        except Exception:
            ok = False
    _smtp_ok = ok
    _smtp_ate = time.time() + (300 if ok else 15)
    return ok


def remetente_confirmado(forcar: bool = False) -> bool:
    global _remetente_ate, _remetente_ok
    import time

    if not forcar and time.time() < _remetente_ate:
        return _remetente_ok
    chave = _ler_chave()
    gmail = _gmail().lower()
    ok = False
    if chave and gmail:
        import json
        import urllib.request

        req = urllib.request.Request(
            "https://api.brevo.com/v3/senders?limit=50",
            headers={"api-key": chave, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            for item in data.get("senders") or []:
                email = str(item.get("email") or "").lower()
                if email == gmail and item.get("active"):
                    ok = True
                    break
        except Exception:
            ok = False
    _remetente_ok = ok
    _remetente_ate = time.time() + (300 if ok else 20)
    return ok


def aplicar_env() -> None:
    """Aponta o SMTP do Hermes para cá. Não mexe na senha nem no IMAP."""
    if not tem_chave():
        return
    envp = HOME / ".env"
    linhas = envp.read_text(encoding="utf-8").splitlines() if envp.exists() else []
    novo = []
    viu_host = viu_porta = False
    for linha in linhas:
        if linha.startswith("EMAIL_SMTP_HOST="):
            novo.append(f"EMAIL_SMTP_HOST={HOST}")
            viu_host = True
        elif linha.startswith("EMAIL_SMTP_PORT="):
            novo.append(f"EMAIL_SMTP_PORT={PORTA}")
            viu_porta = True
        else:
            novo.append(linha)
    if not viu_host:
        novo.append(f"EMAIL_SMTP_HOST={HOST}")
    if not viu_porta:
        novo.append(f"EMAIL_SMTP_PORT={PORTA}")
    envp.write_text("\n".join(novo) + "\n", encoding="utf-8")


def pacote_ca() -> str:
    """CA local + as CAs do sistema. Sem as do sistema, o IMAP do Gmail quebra."""
    _garantir_cert()
    sistema = ""
    try:
        import certifi
        sistema = Path(certifi.where()).read_text(encoding="utf-8")
    except Exception:
        sistema = ""
    if not sistema:
        for caminho in ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem"):
            if Path(caminho).exists():
                sistema = Path(caminho).read_text(encoding="utf-8")
                break
    nossa = (_CERT / "ca.pem").read_text(encoding="utf-8")
    destino = _CERT / "bundle.pem"
    destino.write_text(sistema + "\n" + nossa, encoding="utf-8")
    return str(destino)


def _garantir_cert() -> None:
    cert = _CERT / "cert.pem"
    key = _CERT / "key.pem"
    if cert.exists() and key.exists() and (_CERT / "ca.pem").exists():
        return
    _CERT.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "orbe-saida")])
    agora = datetime.now(timezone.utc)
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(ca_ski, critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert_pub = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)]))
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address(HOST))]),
            critical=False,
        )
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (_CERT / "ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert.write_bytes(cert_pub.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


def ligar() -> None:
    global _servidor
    if not tem_chave():
        return
    with _trava:
        if _servidor is not None:
            return
        _garantir_cert()
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORTA))
        sock.listen(8)
        sock.settimeout(1.0)
        _servidor = sock
        threading.Thread(target=_aceitar, args=(sock,), daemon=True, name="email-saida").start()


def _aceitar(sock: socket.socket) -> None:
    while True:
        try:
            cli, end = sock.accept()
        except socket.timeout:
            continue
        except Exception:
            return
        if end[0] != HOST:
            cli.close()
            continue
        threading.Thread(target=_sessao, args=(cli,), daemon=True).start()


def _sessao(sock: socket.socket) -> None:
    try:
        _falar(sock, b"220 saida.orbe ESMTP\r\n")
        tls = False
        while True:
            linha = _ler(sock)
            if not linha:
                break
            cmd, _, arg = linha.strip().partition(" ")
            cmd = cmd.upper()
            if cmd in {"EHLO", "HELO"}:
                linhas = [b"250-saida.orbe", b"250-AUTH LOGIN PLAIN"]
                if not tls:
                    linhas.insert(1, b"250-STARTTLS")
                linhas[-1] = linhas[-1].replace(b"-", b" ", 1)
                _falar(sock, b"\r\n".join(linhas) + b"\r\n")
            elif cmd == "STARTTLS" and not tls:
                _falar(sock, b"220 pronto\r\n")
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(_CERT / "cert.pem", _CERT / "key.pem")
                sock = ctx.wrap_socket(sock, server_side=True)
                tls = True
            elif cmd == "AUTH":
                if not _auth(sock, arg):
                    break
            elif cmd == "MAIL":
                _falar(sock, b"250 ok\r\n")
            elif cmd == "RCPT":
                _falar(sock, b"250 ok\r\n")
            elif cmd == "DATA":
                _falar(sock, b"354 manda\r\n")
                bruto = _ler_data(sock)
                ok, motivo = _entregar(bruto)
                if ok:
                    _falar(sock, b"250 entregue\r\n")
                else:
                    _falar(sock, f"450 {motivo}\r\n".encode())
            elif cmd in {"QUIT", "RSET", "NOOP"}:
                _falar(sock, b"221 tchau\r\n" if cmd == "QUIT" else b"250 ok\r\n")
                if cmd == "QUIT":
                    break
            else:
                _falar(sock, b"502 nao\r\n")
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _auth(sock: socket.socket, arg: str) -> bool:
    pedaco = arg.strip()
    tipo, _, resto = pedaco.partition(" ")
    tipo = tipo.upper()
    if tipo == "PLAIN":
        token = resto.strip()
        if not token:
            _falar(sock, b"334 \r\n")
            token = _ler(sock).strip()
        try:
            base64.b64decode(token)
        except Exception:
            _falar(sock, b"535 nao\r\n")
            return False
        _falar(sock, b"235 ok\r\n")
        return True
    if tipo == "LOGIN":
        _falar(sock, b"334 VXNlcm5hbWU6\r\n")
        _ler(sock)
        _falar(sock, b"334 UGFzc3dvcmQ6\r\n")
        _ler(sock)
        _falar(sock, b"235 ok\r\n")
        return True
    _falar(sock, b"504 nao\r\n")
    return False


def _entregar(bruto: str) -> tuple[bool, str]:
    msg = Parser().parsestr(bruto)
    de = _endereco(msg.get("From") or "") or _gmail()
    para = _endereco(msg.get("To") or "")
    if not de or not para:
        return False, "faltou destinatario"
    assunto = str(msg.get("Subject") or "Orbe")[:180]
    corpo = _texto(msg)
    ok, motivo = _brevo(de, para, assunto, corpo, msg)
    if ok:
        return True, ""
    if _pc_capaz and _pedir_pc(de, para, assunto, corpo):
        return True, ""
    return False, motivo or "sem saida"


def _brevo(de: str, para: str, assunto: str, corpo: str, msg) -> tuple[bool, str]:
    chave = _ler_chave()
    if not chave:
        return False, "falta a chave"
    if eh_smtp():
        return _brevo_smtp(de, para, assunto, corpo, chave)
    import json
    import urllib.request

    payload = {
        "sender": {"email": de},
        "to": [{"email": para}],
        "subject": assunto,
        "textContent": corpo or "(sem texto)",
        "replyTo": {"email": de},
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode(),
        headers={"api-key": chave, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            r.read()
        return True, ""
    except Exception as exc:
        codigo = getattr(exc, "code", None)
        if codigo == 400:
            return False, "o Brevo ainda nao confirmou esse remetente"
        return False, "o Brevo nao aceitou a mensagem"


def _brevo_smtp(de: str, para: str, assunto: str, corpo: str, chave: str) -> tuple[bool, str]:
    login = _ler_login()
    if not login:
        return False, "falta o login"
    import smtplib
    from email.message import EmailMessage

    mensagem = EmailMessage()
    mensagem["From"] = de
    mensagem["To"] = para
    mensagem["Subject"] = assunto[:180]
    mensagem.set_content(corpo or "(sem texto)")
    try:
        with smtplib.SMTP("smtp-relay.brevo.com", 2525, timeout=25) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(login, chave)
            s.send_message(mensagem)
        return True, ""
    except Exception:
        return False, "o Brevo nao aceitou a mensagem"


def _pedir_pc(de: str, para: str, assunto: str, corpo: str) -> bool:
    import uuid

    item = {"id": uuid.uuid4().hex[:12], "de": de, "para": para, "assunto": assunto, "corpo": corpo[:8000]}
    with _trava:
        _fila_pc.append(item)
    return False


def marcar_pc(capaz: bool) -> None:
    global _pc_capaz
    _pc_capaz = capaz


def pegar_pc() -> dict | None:
    with _trava:
        if not _fila_pc:
            return None
        return _fila_pc.pop(0)


def _endereco(valor: str) -> str:
    m = re.search(r"[^<>\s]+@[^<>\s]+", valor or "")
    email = m.group(0).strip().lower() if m else ""
    return email if _EMAIL.match(email) else ""


def _texto(msg) -> str:
    if msg.is_multipart():
        for parte in msg.walk():
            if parte.get_content_type() == "text/plain":
                payload = parte.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode(parte.get_content_charset() or "utf-8", "replace")
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode(msg.get_content_charset() or "utf-8", "replace")
    return str(msg.get_payload() or "")


def _falar(sock: socket.socket, dados: bytes) -> None:
    sock.sendall(dados)


def _ler(sock: socket.socket) -> str:
    buf = b""
    while b"\n" not in buf and len(buf) < 8000:
        ped = sock.recv(1024)
        if not ped:
            break
        buf += ped
    return buf.decode("utf-8", "replace")


def _ler_data(sock: socket.socket) -> str:
    buf = b""
    while b"\r\n.\r\n" not in buf and len(buf) < 1_000_000:
        ped = sock.recv(4096)
        if not ped:
            break
        buf += ped
    texto = buf.decode("utf-8", "replace")
    if texto.endswith("\r\n.\r\n"):
        texto = texto[:-5]
    return texto


def pagina(aviso: str = "", ok: bool = False) -> str:
    if pronta():
        estado = "Saída ligada. O teste do e-mail já pode passar."
    elif tem_chave() and not tem_login():
        estado = "Chave salva. Falta o login de Suas configurações SMTP."
    elif tem_chave():
        estado = "Ainda não entrou no Brevo. Confere o login e se o Gmail está em Remetentes."
    else:
        estado = "Ainda sem chave."
    cor = "#1f7a4d" if ok or pronta() else "#8a5a00"
    aviso_html = f"<p style='color:{cor}'>{aviso}</p>" if aviso else ""
    return f"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><title>Saída de e-mail</title></head>
<body style="font:16px/1.45 system-ui,sans-serif;max-width:38rem;margin:2rem auto;padding:0 1rem;color:#1c1917">
<h1 style="font-size:1.3rem">Saída de e-mail</h1>
<p>Não autoriza endereço de IP no Brevo. Se autorizar, ele trava o servidor.</p>
<p><b>{estado}</b></p>
{aviso_html}
<ol>
<li>Fecha o aviso de IP. Não coloca IP nenhum.</li>
<li>Em Remetentes, o Gmail tem que estar confirmado.</li>
<li>Em SMTP e API, copia o Login de Suas configurações SMTP. Não é o e-mail do Gmail.</li>
<li>Cola aqui o login e a chave SMTP que apareceu uma vez só.</li>
</ol>
<form method="post">
<label>Login do SMTP<br>
<input name="login" autocomplete="off" style="width:100%;padding:.5rem;margin:.4rem 0 1rem">
</label>
<label>Chave SMTP<br>
<input name="chave" type="password" autocomplete="off" style="width:100%;padding:.5rem;margin:.4rem 0 1rem">
</label><br>
<button type="submit" style="padding:.5rem 1rem">Salvar</button>
</form>
</body></html>"""
