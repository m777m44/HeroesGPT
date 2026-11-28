import { Data } from "effect"

export class UnauthorizedError extends Data.TaggedError("UnauthorizedError")<{
  readonly message: string
}> {}

export class ForbiddenError extends Data.TaggedError("ForbiddenError")<{
  readonly message: string
}> {}

export class NotFoundError extends Data.TaggedError("NotFoundError")<{
  readonly entity: string
  readonly id?: string
  readonly message?: string
}> {}

export class ValidationError extends Data.TaggedError("ValidationError")<{
  readonly message: string
  readonly field?: string
}> {}

export class ConflictError extends Data.TaggedError("ConflictError")<{
  readonly message: string
}> {}

export class PlaidApiError extends Data.TaggedError("PlaidApiError")<{
  readonly code: string
  readonly message: string
  readonly retryable?: boolean
  readonly status?: number
}> {}

export class SqlGuardError extends Data.TaggedError("SqlGuardError")<{
  readonly message: string
}> {}

export class DatabaseError extends Data.TaggedError("DatabaseError")<{
  readonly message: string
  readonly cause?: unknown
}> {}

export type RadiantError =
  | UnauthorizedError
  | ForbiddenError
  | NotFoundError
  | ValidationError
  | ConflictError
  | PlaidApiError
  | SqlGuardError
  | DatabaseError
