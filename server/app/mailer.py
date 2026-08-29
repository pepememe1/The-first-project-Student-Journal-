"""
mailer.py — отправка писем (креды регистрации, восстановление пароля).

Работает через SMTP Mail.ru (по умолчанию smtp.mail.ru:465, SSL) под ЛИЧНЫМ ящиком-
«двигателем», а в поле From показывается адрес домена (admin@esstu-gradebook.ru). Все
секреты — из окружения (server/.env), НЕ в коде:

    GRADEBOOK_SMTP_HOST=smtp.mail.ru
    GRADEBOOK_SMTP_PORT=465
    GRADEBOOK_SMTP_USER=<личный_ящик@mail.ru>       # логин для SMTP
    GRADEBOOK_SMTP_PASS=<пароль_приложения_16_симв> # НЕ обычный пароль!
    GRADEBOOK_SMTP_FROM=admin@esstu-gradebook.ru    # что видит получатель
    GRADEBOOK_SMTP_FROM_NAME=GradeBookAI

Для доставляемости в DNS домена нужна SPF-запись: TXT @  "v=spf1 include:_spf.mail.ru ~all".
Если SMTP не настроен (нет HOST/USER/PASS) — send_email вернёт False, а вызывающий код
покажет админу сгенерированные креды для ручной передачи (регистрация не ломается).
"""
import os
import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr


def send_email(to: str, subject: str, body: str, html: str = "") -> bool:
    """Отправляет письмо. True — ушло, False — не настроено/ошибка (не роняем поток)."""
    host = os.environ.get("GRADEBOOK_SMTP_HOST", "").strip()
    user = os.environ.get("GRADEBOOK_SMTP_USER", "").strip()
    from . import secrets_source
    pwd = secrets_source.get("GRADEBOOK_SMTP_PASS")
    if not (host and user and pwd):
        return False
    port = int(os.environ.get("GRADEBOOK_SMTP_PORT", "465"))
    from_addr = os.environ.get("GRADEBOOK_SMTP_FROM", user).strip()
    from_name = os.environ.get("GRADEBOOK_SMTP_FROM_NAME", "GradeBookAI").strip()

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = from_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=25) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=25) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception as e:
        print(f"[mailer] не удалось отправить письмо на {to}: {e}")
        return False


def _brand_html(title: str, lines: list) -> str:
    """Простой фирменный HTML-шаблон письма (акцент GB, читаемая карточка)."""
    body = "".join(f"<p style='margin:6px 0;font-size:15px;color:#1f2a2d'>{l}</p>" for l in lines)
    return f"""<div style="background:#eef3f4;padding:28px 0;font-family:Arial,sans-serif">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;
              border:1px solid #d9e3e5">
    <div style="background:#147C8B;padding:18px 24px;color:#fff;font-size:20px;font-weight:800">
      GradeBookAI · Технологический колледж ВСГУТУ</div>
    <div style="padding:22px 24px">
      <h2 style="margin:0 0 12px;font-size:18px;color:#147C8B">{title}</h2>
      {body}
      <p style="margin:18px 0 0;font-size:12px;color:#8a9a9c">
        Это письмо отправлено автоматически. Если вы не запрашивали доступ — просто
        проигнорируйте его.</p>
    </div>
  </div></div>"""
