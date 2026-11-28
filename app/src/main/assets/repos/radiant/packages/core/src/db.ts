import { connect, type Connection, type ExecutedQuery } from "@planetscale/database"
import { Context, Effect, Layer } from "effect"
import { DatabaseError } from "./errors"

export type SqlParam = string | number | boolean | null | Date

export interface QueryResult<T = Record<string, unknown>> {
  readonly rows: ReadonlyArray<T>
  readonly rowsAffected: number
}

export interface DbExecutor {
  readonly query: <T = Record<string, unknown>>(
    sql: string,
    params?: ReadonlyArray<SqlParam>,
  ) => Effect.Effect<QueryResult<T>, DatabaseError>
  readonly execute: (
    sql: string,
    params?: ReadonlyArray<SqlParam>,
  ) => Effect.Effect<QueryResult<Record<string, unknown>>, DatabaseError>
}

export interface DatabaseInterface extends DbExecutor {
  /** Execute a read-only query against the read-only PlanetScale reader credential. */
  readonly queryReadOnly: <T = Record<string, unknown>>(
    sql: string,
    params?: ReadonlyArray<SqlParam>,
  ) => Effect.Effect<QueryResult<T>, DatabaseError>
  /** Execute operations atomically in a SQL transaction on the primary connection. */
  readonly transaction: <A, E, R>(
    fn: (tx: DbExecutor) => Effect.Effect<A, E, R>,
  ) => Effect.Effect<A, E | DatabaseError, R>
}

export class Database extends Context.Service<Database, DatabaseInterface>()("@radiant/core/Database") {}

const TRANSIENT_TRANSPORT_MESSAGES = new Set([
  "Network connection lost.",
  "fetch failed",
])

const isTransientTransport = (err: unknown): boolean =>
  err instanceof Error && TRANSIENT_TRANSPORT_MESSAGES.has(err.message)

const normalizeParam = (p: SqlParam): string | number | boolean | null =>
  p instanceof Date ? p.toISOString().slice(0, 23).replace("T", " ") : p

const execOnConnection = <T>(
  conn: Pick<Connection, "execute">,
  sql: string,
  params: ReadonlyArray<SqlParam> = [],
  allowRetry = false,
): Effect.Effect<QueryResult<T>, DatabaseError> => {
  const run = Effect.tryPromise({
    try: async (): Promise<QueryResult<T>> => {
      const res: ExecutedQuery = await conn.execute(sql, params.map(normalizeParam))
      return {
        rows: res.rows as ReadonlyArray<T>,
        rowsAffected: res.rowsAffected ?? 0,
      }
    },
    catch: (cause) =>
      new DatabaseError({
        message: cause instanceof Error ? cause.message : String(cause),
        cause,
      }),
  })

  if (!allowRetry) return run

  return Effect.catchIf(
    run,
    (e) => isTransientTransport(e.cause),
    () => Effect.andThen(Effect.sleep("50 millis"), run),
  )
}

export const makePlanetscaleDatabase = (config: {
  readonly url: string
  readonly readUrl?: string
}): DatabaseInterface => {
  const primary = connect({ url: config.url })
  const reader = connect({ url: config.readUrl ?? config.url })

  const query = <T = Record<string, unknown>>(
    sql: string,
    params?: ReadonlyArray<SqlParam>,
  ) => execOnConnection<T>(primary, sql, params, true)

  const execute = (sql: string, params?: ReadonlyArray<SqlParam>) =>
    execOnConnection<Record<string, unknown>>(primary, sql, params, false)

  const queryReadOnly = <T = Record<string, unknown>>(
    sql: string,
    params?: ReadonlyArray<SqlParam>,
  ) => execOnConnection<T>(reader, sql, params, true)

  const transaction = <A, E, R>(
    fn: (tx: DbExecutor) => Effect.Effect<A, E, R>,
  ): Effect.Effect<A, E | DatabaseError, R> =>
    Effect.gen(function* () {
      const ctx = yield* Effect.context<R>()
      const res = yield* Effect.tryPromise({
        try: () =>
          primary.transaction(async (psTx) => {
            const txExec: DbExecutor = {
              query: <T = Record<string, unknown>>(sql: string, params?: ReadonlyArray<SqlParam>) =>
                execOnConnection<T>(psTx, sql, params, false),
              execute: (sql: string, params?: ReadonlyArray<SqlParam>) =>
                execOnConnection<Record<string, unknown>>(psTx, sql, params, false),
            }
            const exit = await Effect.runPromiseExit(Effect.provideContext(fn(txExec), ctx))
            if (exit._tag === "Success") return { ok: true as const, value: exit.value }
            return { ok: false as const, cause: exit.cause }
          }),
        catch: (cause) =>
          cause instanceof DatabaseError
            ? cause
            : new DatabaseError({
                message: cause instanceof Error ? cause.message : String(cause),
                cause,
              }),
      })
      if (res.ok) return res.value
      return yield* Effect.failCause(res.cause)
    })

  return Database.of({
    query,
    execute,
    queryReadOnly,
    transaction,
  })
}

export const layerPlanetscale = (config: {
  readonly url: string
  readonly readUrl?: string
}) => Layer.succeed(Database, makePlanetscaleDatabase(config))

export const parseJsonColumn = <T>(val: unknown, fallback: T): T => {
  if (val === null || val === undefined) return fallback
  if (typeof val === "string") {
    try {
      return JSON.parse(val) as T
    } catch {
      return fallback
    }
  }
  return val as T
}

export const toBool = (val: unknown): boolean => val === true || val === 1 || val === "1"

export const toNum = (val: unknown): number => {
  if (typeof val === "number") return val
  if (typeof val === "bigint") return Number(val)
  if (typeof val === "string") return Number(val)
  return 0
}

export const toNullableNum = (val: unknown): number | null =>
  val === null || val === undefined ? null : toNum(val)
