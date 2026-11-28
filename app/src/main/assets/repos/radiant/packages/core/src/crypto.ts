import { Effect } from "effect"
import { ValidationError } from "./errors"

const encoder = new TextEncoder()
const decoder = new TextDecoder()

const toHex = (bytes: Uint8Array): string =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")

const toBase64Url = (bytes: Uint8Array): string =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "")

const fromBase64 = (value: string): Uint8Array<ArrayBuffer> => {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/")
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4)
  const binary = atob(padded)
  const buf = new ArrayBuffer(binary.length)
  const out = new Uint8Array(buf)
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i)
  return out
}

export const sha256Hex = (input: string): Effect.Effect<string> =>
  Effect.promise(async () => {
    const digest = await crypto.subtle.digest("SHA-256", encoder.encode(input))
    return toHex(new Uint8Array(digest))
  })

export const pkceS256Challenge = (verifier: string): Effect.Effect<string> =>
  Effect.promise(async () => {
    const digest = await crypto.subtle.digest("SHA-256", encoder.encode(verifier))
    return toBase64Url(new Uint8Array(digest))
  })

export const randomToken = (prefix: string, byteLength = 32): string => {
  const bytes = new Uint8Array(byteLength)
  crypto.getRandomValues(bytes)
  return `${prefix}${toBase64Url(bytes)}`
}

const USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"

export const randomUserCode = (): string => {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  const chars = Array.from(bytes, (b) => USER_CODE_ALPHABET[b % USER_CODE_ALPHABET.length]!)
  return `${chars.slice(0, 4).join("")}-${chars.slice(4).join("")}`
}

export const constantTimeEqual = (a: string, b: string): boolean => {
  const ab = encoder.encode(a)
  const bb = encoder.encode(b)
  if (ab.length !== bb.length) return false
  let diff = 0
  for (let i = 0; i < ab.length; i++) diff |= ab[i]! ^ bb[i]!
  return diff === 0
}

const importAesKey = async (keyBase64: string, usages: ReadonlyArray<KeyUsage>): Promise<CryptoKey> => {
  const raw = fromBase64(keyBase64)
  if (raw.byteLength !== 32) {
    throw new Error(`Encryption key must be 32 bytes (got ${raw.byteLength})`)
  }
  return crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, [...usages])
}

export const encryptSecret = (
  plaintext: string,
  keyBase64: string,
  version: string,
): Effect.Effect<string, ValidationError> =>
  Effect.tryPromise({
    try: async () => {
      const key = await importAesKey(keyBase64, ["encrypt"])
      const iv = new Uint8Array(new ArrayBuffer(12))
      crypto.getRandomValues(iv)
      const cipher = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv },
        key,
        encoder.encode(plaintext),
      )
      return `${version}:${toBase64Url(iv)}:${toBase64Url(new Uint8Array(cipher))}`
    },
    catch: (cause) =>
      new ValidationError({
        message: `Failed to encrypt secret: ${cause instanceof Error ? cause.message : String(cause)}`,
      }),
  })

export const decryptSecret = (
  encoded: string,
  keysByVersion: Readonly<Record<string, string>>,
): Effect.Effect<string, ValidationError> =>
  Effect.tryPromise({
    try: async () => {
      const parts = encoded.split(":")
      if (parts.length !== 3) throw new Error("Malformed encrypted secret envelope")
      const [version, ivB64, cipherB64] = parts as [string, string, string]
      const keyB64 = keysByVersion[version]
      if (!keyB64) throw new Error(`Unknown encryption key version: ${version}`)
      const key = await importAesKey(keyB64, ["decrypt"])
      const iv = fromBase64(ivB64)
      const cipher = fromBase64(cipherB64)
      const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, cipher)
      return decoder.decode(plain)
    },
    catch: (cause) =>
      new ValidationError({
        message: `Failed to decrypt secret: ${cause instanceof Error ? cause.message : String(cause)}`,
      }),
  })
