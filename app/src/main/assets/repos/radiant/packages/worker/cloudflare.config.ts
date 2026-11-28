import { bindings, defineConfig, triggers } from "cf/config"

const BASE_PATH = "/labs/radiant"

export default defineConfig(({ mode }) => {
  if (mode !== "dev" && mode !== "production") {
    throw new Error("Select mode dev or production")
  }
  const dev = mode === "dev"
  const name = `radiant-${mode}`
  const host = dev ? "dev.anoma.ly" : "anoma.ly"
  const queueName = `${name}-plaid-sync`
  const dlqName = `${name}-plaid-sync-dlq`

  return {
    accountId: dev ? "d8e944f537ceef3f06a5bd3aec1d7a53" : "15d29c8639fd3733b1b5486a2acfd968",
    worker: {
      name,
      entrypoint: "./src/index.ts",
      compatibilityDate: "2026-11-01",
      compatibilityFlags: ["nodejs_compat"],
      workersDev: false,
      previewUrls: false,
      triggers: [
        triggers.fetch({ pattern: `${host}${BASE_PATH}`, zone: host }),
        triggers.fetch({ pattern: `${host}${BASE_PATH}/*`, zone: host }),
        triggers.fetch({ pattern: `${host}/.well-known/oauth-protected-resource${BASE_PATH}*`, zone: host }),
        triggers.fetch({ pattern: `${host}/.well-known/oauth-authorization-server${BASE_PATH}*`, zone: host }),
        triggers.queue({
          name: queueName,
          deadLetterQueue: dlqName,
          maxBatchSize: 5,
          maxBatchTimeout: 5,
          maxRetries: 5,
          retryDelay: 30,
        }),
        triggers.scheduled({ schedule: "0 6 * * *" }),
      ],
      env: {
        STAGE: bindings.text(mode),
        BASE_PATH: bindings.text(BASE_PATH),
        ACCOUNT_ISSUER: bindings.text(dev ? "https://account.dev.anoma.ly" : "https://account.anoma.ly"),
        ACCOUNT_CLIENT_ID: bindings.text("radiant"),
        PLAID_ENV: bindings.text(dev ? "sandbox" : "production"),
        ENCRYPTION_KEY_VERSION: bindings.text("v1"),
        PLAID_SYNC_QUEUE: bindings.queue({ name: queueName }),
        DATABASE_URL: bindings.secret(),
        DATABASE_READ_URL: bindings.secret(),
        ENCRYPTION_KEY: bindings.secret(),
        SESSION_SECRET: bindings.secret(),
        PLAID_CLIENT_ID: bindings.secret(),
        PLAID_SECRET: bindings.secret(),
      },
      observability: { enabled: true, redactQueryString: true },
    },
  }
})
