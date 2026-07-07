/**
 * webauthn.js — Клиентская часть passkeys (вход по Face ID / отпечатку).
 *
 * Сервер отдаёт опции в стандартном WebAuthn-JSON (бинарные поля — base64url-строки),
 * а браузерное API navigator.credentials.create/get требует ArrayBuffer — поэтому тут
 * ручная конвертация в обе стороны (без внешних зависимостей, работает во всех браузерах
 * с поддержкой WebAuthn). Обратно результат устройства сериализуем в тот же JSON-формат,
 * который понимает серверная библиотека py_webauthn.
 */
import { authApi } from './endpoints'

function b64urlToBuf(s) {
  const pad = '='.repeat((4 - (s.length % 4)) % 4)
  const b64 = (s + pad).replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(b64)
  const buf = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i)
  return buf.buffer
}

function bufToB64url(buf) {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Поддерживает ли браузер passkeys вообще. */
export function passkeySupported() {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials
}

/** Есть ли на устройстве встроенный биометрический аутентификатор (Face ID/отпечаток). */
export async function platformAuthenticatorAvailable() {
  try {
    return passkeySupported() &&
      (await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable())
  } catch {
    return false
  }
}

function serializeCredential(cred, isRegistration) {
  const r = cred.response
  const out = {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment || undefined,
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    response: { clientDataJSON: bufToB64url(r.clientDataJSON) },
  }
  if (isRegistration) {
    out.response.attestationObject = bufToB64url(r.attestationObject)
    if (r.getTransports) out.response.transports = r.getTransports()
  } else {
    out.response.authenticatorData = bufToB64url(r.authenticatorData)
    out.response.signature = bufToB64url(r.signature)
    out.response.userHandle = r.userHandle ? bufToB64url(r.userHandle) : null
  }
  return out
}

/** Включить вход по биометрии для ТЕКУЩЕГО пользователя (нужен активный вход). */
export async function enablePasskey(deviceName) {
  const { data: options } = await authApi.webauthnRegisterBegin()
  const pub = { ...options, challenge: b64urlToBuf(options.challenge) }
  pub.user = { ...options.user, id: b64urlToBuf(options.user.id) }
  if (options.excludeCredentials) {
    pub.excludeCredentials = options.excludeCredentials.map((c) => ({ ...c, id: b64urlToBuf(c.id) }))
  }
  const cred = await navigator.credentials.create({ publicKey: pub })
  const payload = serializeCredential(cred, true)
  await authApi.webauthnRegisterComplete({
    credential: payload,
    device_name: deviceName || 'Это устройство',
    transports: payload.response.transports || [],
  })
}

/** Войти по биометрии без пароля. Возвращает данные сессии {access_token, ...}. */
export async function loginWithPasskey(login = '') {
  const { data: options } = await authApi.webauthnLoginBegin(login)
  const pub = { ...options, challenge: b64urlToBuf(options.challenge) }
  if (options.allowCredentials) {
    pub.allowCredentials = options.allowCredentials.map((c) => ({ ...c, id: b64urlToBuf(c.id) }))
  }
  const cred = await navigator.credentials.get({ publicKey: pub })
  const payload = serializeCredential(cred, false)
  const { data } = await authApi.webauthnLoginComplete({ credential: payload, login })
  return data
}
