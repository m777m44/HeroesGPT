import { connect } from "@planetscale/database"
import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"

interface JournalEntry {
  idx: number
  tag: string
  when: number
}

interface Journal {
  entries: ReadonlyArray<JournalEntry>
}

const url = process.env.DATABASE_URL
if (!url) {
  console.error("DATABASE_URL is required")
  process.exit(1)
}

const conn = connect({ url })
const migrationsDir = join(import.meta.dir, "../../../migrations")

await conn.execute(`
  CREATE TABLE IF NOT EXISTS __drizzle_migrations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    hash VARCHAR(128) NOT NULL UNIQUE,
    created_at BIGINT NOT NULL
  )
`)

const existing = await conn.execute("SELECT hash FROM __drizzle_migrations")
const applied = new Set(existing.rows.map((r) => String((r as Record<string, unknown>).hash)))

const journalPath = join(migrationsDir, "meta/_journal.json")
let files: Array<{ tag: string; sql: string }> = []

try {
  const journal = JSON.parse(readFileSync(journalPath, "utf8")) as Journal
  files = journal.entries.map((entry) => ({
    tag: entry.tag,
    sql: readFileSync(join(migrationsDir, `${entry.tag}.sql`), "utf8"),
  }))
} catch {
  // Drizzle beta 1.0 uses folder-per-migration (<dir>/migration.sql)
  const dirs = readdirSync(migrationsDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && d.name !== "meta")
    .map((d) => d.name)
    .sort()
  files = dirs.map((dir) => ({
    tag: dir,
    sql: readFileSync(join(migrationsDir, dir, "migration.sql"), "utf8"),
  }))
}

for (const file of files) {
  if (applied.has(file.tag)) {
    console.log(`skip ${file.tag}`)
    continue
  }
  const statements = file.sql
    .split("--> statement-breakpoint")
    .map((s) => s.trim())
    .filter((s) => s.length > 0)

  for (const stmt of statements) {
    await conn.execute(stmt)
  }

  await conn.execute("INSERT INTO __drizzle_migrations (hash, created_at) VALUES (?, ?)", [
    file.tag,
    Date.now(),
  ])
  console.log(`applied ${file.tag} (${statements.length} statements)`)
}

console.log("migrations complete")
