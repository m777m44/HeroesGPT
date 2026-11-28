CREATE TABLE `account_overlay` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`batch_id` varchar(36) NOT NULL,
	`account_id` varchar(36) NOT NULL,
	`seq` bigint NOT NULL,
	`nickname` varchar(255),
	`account_group` varchar(120),
	`owner_label` varchar(120),
	`is_hidden` boolean,
	`is_excluded_from_net_worth` boolean,
	`notes` text,
	`active` boolean NOT NULL DEFAULT true,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `api_token` (
	`id` varchar(36) PRIMARY KEY,
	`workspace_id` varchar(36) NOT NULL,
	`user_id` varchar(36) NOT NULL,
	`name` varchar(120) NOT NULL,
	`role` varchar(16) NOT NULL,
	`token_hash` varchar(64) NOT NULL,
	`last_used_at` timestamp(3),
	`expires_at` timestamp(3),
	`revoked_at` timestamp(3),
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT `uq_api_token_hash` UNIQUE INDEX(`token_hash`)
);
--> statement-breakpoint
CREATE TABLE `connect_token` (
	`token_hash` varchar(64) PRIMARY KEY,
	`workspace_id` varchar(36) NOT NULL,
	`user_id` varchar(36) NOT NULL,
	`mode` varchar(16) NOT NULL,
	`item_id` varchar(128),
	`expires_at` timestamp(3) NOT NULL,
	`consumed_at` timestamp(3),
	`created_at` timestamp(3) NOT NULL DEFAULT (now())
);
--> statement-breakpoint
CREATE TABLE `device_code` (
	`id` varchar(36) PRIMARY KEY,
	`device_code_hash` varchar(64) NOT NULL,
	`user_code` varchar(16) NOT NULL,
	`client_name` varchar(120) NOT NULL,
	`status` varchar(24) NOT NULL,
	`user_id` varchar(36),
	`interval_seconds` int NOT NULL DEFAULT 5,
	`last_polled_at` timestamp(3),
	`expires_at` timestamp(3) NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT `uq_device_code_hash` UNIQUE INDEX(`device_code_hash`),
	CONSTRAINT `uq_device_user_code` UNIQUE INDEX(`user_code`)
);
--> statement-breakpoint
CREATE TABLE `effective_transaction` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`source` varchar(16) NOT NULL,
	`account_id` varchar(36),
	`institution_id` varchar(128),
	`date` varchar(10) NOT NULL,
	`raw_date` varchar(10) NOT NULL,
	`amount_cents` bigint NOT NULL,
	`raw_amount_cents` bigint NOT NULL,
	`currency` varchar(8) NOT NULL DEFAULT 'USD',
	`merchant_name` varchar(255),
	`description` varchar(512) NOT NULL,
	`raw_name` varchar(512) NOT NULL,
	`category` varchar(255),
	`category_top` varchar(128),
	`raw_category` varchar(255),
	`payment_channel` varchar(64),
	`pending` boolean NOT NULL DEFAULT false,
	`is_transfer` boolean NOT NULL DEFAULT false,
	`transfer_pair_id` varchar(36),
	`is_excluded` boolean NOT NULL DEFAULT false,
	`has_splits` boolean NOT NULL DEFAULT false,
	`has_overlay` boolean NOT NULL DEFAULT false,
	`recurring_group` varchar(128),
	`tags_json` json NOT NULL,
	`tags_text` text NOT NULL,
	`notes` text,
	`custom_fields_json` json,
	`provenance_json` json NOT NULL,
	`applied_rule_ids_json` json NOT NULL,
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `manual_transaction` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`batch_id` varchar(36) NOT NULL,
	`account_id` varchar(36),
	`date` varchar(10) NOT NULL,
	`amount_cents` bigint NOT NULL,
	`currency` varchar(8) NOT NULL DEFAULT 'USD',
	`merchant_name` varchar(255),
	`description` varchar(512) NOT NULL,
	`category` varchar(255),
	`tags_json` json NOT NULL,
	`notes` text,
	`is_transfer` boolean NOT NULL DEFAULT false,
	`is_excluded` boolean NOT NULL DEFAULT false,
	`custom_fields_json` json,
	`active` boolean NOT NULL DEFAULT true,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `oauth_client` (
	`id` varchar(64) PRIMARY KEY,
	`name` varchar(255) NOT NULL,
	`redirect_uris` json NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now())
);
--> statement-breakpoint
CREATE TABLE `oauth_code` (
	`code_hash` varchar(64) PRIMARY KEY,
	`client_id` varchar(64) NOT NULL,
	`user_id` varchar(36) NOT NULL,
	`redirect_uri` text NOT NULL,
	`code_challenge` varchar(128) NOT NULL,
	`scope` varchar(255) NOT NULL,
	`expires_at` timestamp(3) NOT NULL,
	`consumed_at` timestamp(3),
	`created_at` timestamp(3) NOT NULL DEFAULT (now())
);
--> statement-breakpoint
CREATE TABLE `oauth_flow` (
	`id` varchar(64) PRIMARY KEY,
	`kind` varchar(32) NOT NULL,
	`client_id` varchar(64),
	`redirect_uri` text,
	`state` varchar(512),
	`code_challenge` varchar(128),
	`code_challenge_method` varchar(16),
	`scope` varchar(255),
	`upstream_verifier` varchar(128),
	`upstream_nonce` varchar(128),
	`browser_binding_hash` varchar(64),
	`return_to` text,
	`approved_user_id` varchar(36),
	`expires_at` timestamp(3) NOT NULL,
	`consumed_at` timestamp(3),
	`created_at` timestamp(3) NOT NULL DEFAULT (now())
);
--> statement-breakpoint
CREATE TABLE `oauth_grant` (
	`id` varchar(36) PRIMARY KEY,
	`client_id` varchar(64) NOT NULL,
	`client_name` varchar(255) NOT NULL,
	`user_id` varchar(36) NOT NULL,
	`scope` varchar(255) NOT NULL,
	`access_token_hash` varchar(64) NOT NULL,
	`access_expires_at` timestamp(3) NOT NULL,
	`refresh_token_hash` varchar(64) NOT NULL,
	`refresh_expires_at` timestamp(3) NOT NULL,
	`previous_refresh_hash` varchar(64),
	`revoked_at` timestamp(3),
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT `uq_oauth_grant_access` UNIQUE INDEX(`access_token_hash`),
	CONSTRAINT `uq_oauth_grant_refresh` UNIQUE INDEX(`refresh_token_hash`)
);
--> statement-breakpoint
CREATE TABLE `overlay_batch` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`kind` varchar(32) NOT NULL,
	`actor_type` varchar(16) NOT NULL,
	`actor_id` varchar(36) NOT NULL,
	`client_name` varchar(120),
	`reason` text,
	`payload_json` json,
	`affected_count` int NOT NULL DEFAULT 0,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`reverted_at` timestamp(3),
	`reverted_by` varchar(36),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `plaid_credential` (
	`workspace_id` varchar(36) NOT NULL,
	`item_id` varchar(128) NOT NULL,
	`access_token_enc` text NOT NULL,
	`key_version` varchar(32) NOT NULL,
	`created_by` varchar(36) NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`revoked_at` timestamp(3),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`item_id`),
	CONSTRAINT `uq_plaid_cred_item` UNIQUE INDEX(`item_id`)
);
--> statement-breakpoint
CREATE TABLE `raw_account` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`item_id` varchar(128) NOT NULL,
	`plaid_account_id` varchar(128) NOT NULL,
	`institution_id` varchar(128) NOT NULL,
	`institution_name` varchar(255) NOT NULL,
	`name` varchar(255) NOT NULL,
	`official_name` varchar(255),
	`mask` varchar(32),
	`type` varchar(64) NOT NULL,
	`subtype` varchar(64),
	`currency` varchar(8) NOT NULL DEFAULT 'USD',
	`current_cents` bigint,
	`available_cents` bigint,
	`limit_cents` bigint,
	`raw_json` json NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	`removed_at` timestamp(3),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`),
	CONSTRAINT `uq_raw_account_plaid` UNIQUE INDEX(`workspace_id`,`plaid_account_id`)
);
--> statement-breakpoint
CREATE TABLE `raw_balance_snapshot` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`account_id` varchar(36) NOT NULL,
	`captured_at` timestamp(3) NOT NULL,
	`currency` varchar(8) NOT NULL DEFAULT 'USD',
	`current_cents` bigint,
	`available_cents` bigint,
	`limit_cents` bigint,
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `raw_item` (
	`workspace_id` varchar(36) NOT NULL,
	`item_id` varchar(128) NOT NULL,
	`institution_id` varchar(128) NOT NULL,
	`institution_name` varchar(255) NOT NULL,
	`status` varchar(32) NOT NULL DEFAULT 'healthy',
	`error_code` varchar(128),
	`error_message` text,
	`sync_cursor` varchar(512),
	`last_synced_at` timestamp(3),
	`consent_expires_at` timestamp(3),
	`raw_json` json NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	`disconnected_at` timestamp(3),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`item_id`)
);
--> statement-breakpoint
CREATE TABLE `raw_transaction` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`account_id` varchar(36) NOT NULL,
	`item_id` varchar(128) NOT NULL,
	`plaid_transaction_id` varchar(128) NOT NULL,
	`pending_transaction_id` varchar(128),
	`superseded_by` varchar(36),
	`raw_amount_cents` bigint NOT NULL,
	`currency` varchar(8) NOT NULL DEFAULT 'USD',
	`date` varchar(10) NOT NULL,
	`authorized_date` varchar(10),
	`name` varchar(512) NOT NULL,
	`merchant_name` varchar(255),
	`merchant_entity_id` varchar(128),
	`pfc_primary` varchar(128),
	`pfc_detailed` varchar(128),
	`pfc_confidence` varchar(32),
	`payment_channel` varchar(64),
	`pending` boolean NOT NULL DEFAULT false,
	`counterparty_name` varchar(255),
	`raw_json` json NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	`removed_at` timestamp(3),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`),
	CONSTRAINT `uq_raw_tx_plaid` UNIQUE INDEX(`workspace_id`,`plaid_transaction_id`)
);
--> statement-breakpoint
CREATE TABLE `rule` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`name` varchar(160) NOT NULL,
	`description` text,
	`priority` int NOT NULL DEFAULT 100,
	`enabled` boolean NOT NULL DEFAULT true,
	`stop_on_match` boolean NOT NULL DEFAULT false,
	`match_json` json NOT NULL,
	`actions_json` json NOT NULL,
	`version` int NOT NULL DEFAULT 1,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	`deleted_at` timestamp(3),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `rule_application` (
	`workspace_id` varchar(36) NOT NULL,
	`rule_id` varchar(36) NOT NULL,
	`tx_id` varchar(36) NOT NULL,
	`applied_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`rule_id`,`tx_id`)
);
--> statement-breakpoint
CREATE TABLE `session` (
	`id` varchar(36) PRIMARY KEY,
	`user_id` varchar(36) NOT NULL,
	`token_hash` varchar(64) NOT NULL,
	`expires_at` timestamp(3) NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`revoked_at` timestamp(3),
	CONSTRAINT `uq_session_token` UNIQUE INDEX(`token_hash`)
);
--> statement-breakpoint
CREATE TABLE `sync_run` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`item_id` varchar(128) NOT NULL,
	`trigger` varchar(24) NOT NULL,
	`status` varchar(24) NOT NULL,
	`added_count` int NOT NULL DEFAULT 0,
	`modified_count` int NOT NULL DEFAULT 0,
	`removed_count` int NOT NULL DEFAULT 0,
	`rules_applied_count` int NOT NULL DEFAULT 0,
	`cursor_before` varchar(512),
	`cursor_after` varchar(512),
	`error_code` varchar(128),
	`error_message` text,
	`started_at` timestamp(3) NOT NULL DEFAULT (now()),
	`finished_at` timestamp(3),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `tx_overlay` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`batch_id` varchar(36) NOT NULL,
	`tx_id` varchar(36) NOT NULL,
	`seq` bigint NOT NULL,
	`patch_json` json NOT NULL,
	`active` boolean NOT NULL DEFAULT true,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `tx_split` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`batch_id` varchar(36) NOT NULL,
	`tx_id` varchar(36) NOT NULL,
	`line_index` int NOT NULL,
	`amount_cents` bigint NOT NULL,
	`category` varchar(255),
	`merchant_name` varchar(255),
	`description` varchar(512),
	`tags_json` json NOT NULL,
	`notes` text,
	`is_excluded` boolean NOT NULL DEFAULT false,
	`active` boolean NOT NULL DEFAULT true,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`)
);
--> statement-breakpoint
CREATE TABLE `user` (
	`id` varchar(36) PRIMARY KEY,
	`external_sub` varchar(255) NOT NULL,
	`issuer` varchar(255) NOT NULL,
	`email` varchar(320) NOT NULL,
	`name` varchar(255),
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	`disabled_at` timestamp(3),
	CONSTRAINT `uq_user_issuer_sub` UNIQUE INDEX(`issuer`,`external_sub`)
);
--> statement-breakpoint
CREATE TABLE `workspace` (
	`id` varchar(36) PRIMARY KEY,
	`slug` varchar(80) NOT NULL,
	`name` varchar(120) NOT NULL,
	`currency` varchar(8) NOT NULL DEFAULT 'USD',
	`created_by` varchar(36) NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	`deleted_at` timestamp(3),
	CONSTRAINT `uq_workspace_slug` UNIQUE INDEX(`slug`)
);
--> statement-breakpoint
CREATE TABLE `workspace_invite` (
	`workspace_id` varchar(36) NOT NULL,
	`id` varchar(36) NOT NULL,
	`email` varchar(320) NOT NULL,
	`role` varchar(16) NOT NULL,
	`token_hash` varchar(64) NOT NULL,
	`invited_by` varchar(36) NOT NULL,
	`expires_at` timestamp(3) NOT NULL,
	`accepted_at` timestamp(3),
	`accepted_by` varchar(36),
	`revoked_at` timestamp(3),
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`id`),
	CONSTRAINT `uq_ws_invite_token` UNIQUE INDEX(`token_hash`)
);
--> statement-breakpoint
CREATE TABLE `workspace_member` (
	`workspace_id` varchar(36) NOT NULL,
	`user_id` varchar(36) NOT NULL,
	`role` varchar(16) NOT NULL,
	`created_at` timestamp(3) NOT NULL DEFAULT (now()),
	`updated_at` timestamp(3) NOT NULL DEFAULT (now()),
	CONSTRAINT PRIMARY KEY(`workspace_id`,`user_id`)
);
--> statement-breakpoint
CREATE INDEX `idx_acc_overlay_ws_acc` ON `account_overlay` (`workspace_id`,`account_id`,`active`,`seq`);--> statement-breakpoint
CREATE INDEX `idx_acc_overlay_ws_batch` ON `account_overlay` (`workspace_id`,`batch_id`);--> statement-breakpoint
CREATE INDEX `idx_api_token_ws_user` ON `api_token` (`workspace_id`,`user_id`);--> statement-breakpoint
CREATE INDEX `idx_connect_token_ws` ON `connect_token` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_date_id` ON `effective_transaction` (`workspace_id`,`date`,`id`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_acc_date` ON `effective_transaction` (`workspace_id`,`account_id`,`date`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_cat_date` ON `effective_transaction` (`workspace_id`,`category`,`date`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_cattop_date` ON `effective_transaction` (`workspace_id`,`category_top`,`date`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_merch_date` ON `effective_transaction` (`workspace_id`,`merchant_name`,`date`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_flags_date` ON `effective_transaction` (`workspace_id`,`is_excluded`,`is_transfer`,`date`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_amount` ON `effective_transaction` (`workspace_id`,`amount_cents`);--> statement-breakpoint
CREATE INDEX `idx_eff_tx_ws_overlay_date` ON `effective_transaction` (`workspace_id`,`has_overlay`,`date`);--> statement-breakpoint
CREATE INDEX `idx_manual_tx_ws_batch` ON `manual_transaction` (`workspace_id`,`batch_id`);--> statement-breakpoint
CREATE INDEX `idx_manual_tx_ws_active_date` ON `manual_transaction` (`workspace_id`,`active`,`date`);--> statement-breakpoint
CREATE INDEX `idx_oauth_code_user` ON `oauth_code` (`user_id`);--> statement-breakpoint
CREATE INDEX `idx_oauth_flow_exp` ON `oauth_flow` (`expires_at`);--> statement-breakpoint
CREATE INDEX `idx_oauth_grant_user` ON `oauth_grant` (`user_id`);--> statement-breakpoint
CREATE INDEX `idx_overlay_batch_ws_at` ON `overlay_batch` (`workspace_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_raw_account_ws_item` ON `raw_account` (`workspace_id`,`item_id`);--> statement-breakpoint
CREATE INDEX `idx_raw_account_dedup` ON `raw_account` (`workspace_id`,`institution_id`,`mask`,`type`);--> statement-breakpoint
CREATE INDEX `idx_balance_snap_ws_acc_at` ON `raw_balance_snapshot` (`workspace_id`,`account_id`,`captured_at`);--> statement-breakpoint
CREATE INDEX `idx_balance_snap_ws_at` ON `raw_balance_snapshot` (`workspace_id`,`captured_at`);--> statement-breakpoint
CREATE INDEX `idx_raw_item_ws_status` ON `raw_item` (`workspace_id`,`status`);--> statement-breakpoint
CREATE INDEX `idx_raw_tx_ws_acc_date` ON `raw_transaction` (`workspace_id`,`account_id`,`date`);--> statement-breakpoint
CREATE INDEX `idx_raw_tx_ws_pending` ON `raw_transaction` (`workspace_id`,`pending_transaction_id`);--> statement-breakpoint
CREATE INDEX `idx_rule_ws_enabled_prio` ON `rule` (`workspace_id`,`enabled`,`priority`);--> statement-breakpoint
CREATE INDEX `idx_rule_app_ws_tx` ON `rule_application` (`workspace_id`,`tx_id`);--> statement-breakpoint
CREATE INDEX `idx_session_user` ON `session` (`user_id`);--> statement-breakpoint
CREATE INDEX `idx_sync_run_ws_item_at` ON `sync_run` (`workspace_id`,`item_id`,`started_at`);--> statement-breakpoint
CREATE INDEX `idx_tx_overlay_ws_tx` ON `tx_overlay` (`workspace_id`,`tx_id`,`active`,`seq`);--> statement-breakpoint
CREATE INDEX `idx_tx_overlay_ws_batch` ON `tx_overlay` (`workspace_id`,`batch_id`);--> statement-breakpoint
CREATE INDEX `idx_tx_split_ws_tx` ON `tx_split` (`workspace_id`,`tx_id`,`active`,`line_index`);--> statement-breakpoint
CREATE INDEX `idx_tx_split_ws_batch` ON `tx_split` (`workspace_id`,`batch_id`);--> statement-breakpoint
CREATE INDEX `idx_user_email` ON `user` (`email`);--> statement-breakpoint
CREATE INDEX `idx_ws_invite_ws_email` ON `workspace_invite` (`workspace_id`,`email`);--> statement-breakpoint
CREATE INDEX `idx_ws_member_user` ON `workspace_member` (`user_id`,`workspace_id`);