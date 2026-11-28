import { ulid } from "ulid"

export const Id = {
  user: () => `usr_${ulid()}`,
  session: () => `ses_${ulid()}`,
  workspace: () => `ws_${ulid()}`,
  invite: () => `inv_${ulid()}`,
  account: () => `acc_${ulid()}`,
  snapshot: () => `snp_${ulid()}`,
  tx: () => `tx_${ulid()}`,
  syncRun: () => `syn_${ulid()}`,
  batch: () => `bat_${ulid()}`,
  overlay: () => `ovr_${ulid()}`,
  split: () => `spl_${ulid()}`,
  rule: () => `rul_${ulid()}`,
  grant: () => `grt_${ulid()}`,
  device: () => `dev_${ulid()}`,
  apiToken: () => `tok_${ulid()}`,
  oauthClient: () => `mcp_${ulid()}`,
  oauthFlow: () => `flw_${ulid()}`,
} as const
