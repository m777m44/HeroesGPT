ALTER TABLE `raw_transaction` MODIFY COLUMN `plaid_transaction_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
--> statement-breakpoint
ALTER TABLE `raw_transaction` MODIFY COLUMN `pending_transaction_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
--> statement-breakpoint
ALTER TABLE `raw_transaction` MODIFY COLUMN `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
--> statement-breakpoint
ALTER TABLE `raw_account` MODIFY COLUMN `plaid_account_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
--> statement-breakpoint
ALTER TABLE `raw_account` MODIFY COLUMN `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
--> statement-breakpoint
ALTER TABLE `raw_item` MODIFY COLUMN `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
--> statement-breakpoint
ALTER TABLE `plaid_credential` MODIFY COLUMN `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
--> statement-breakpoint
ALTER TABLE `sync_run` MODIFY COLUMN `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
