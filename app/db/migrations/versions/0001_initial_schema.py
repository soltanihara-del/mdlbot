"""Create the complete Stage 2 PostgreSQL schema.

Revision ID: 0001_initial_schema
Revises: None
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    r"""CREATE TABLE admin_roles (
	code VARCHAR(64) NOT NULL, 
	name_fa VARCHAR(128) NOT NULL, 
	name_en VARCHAR(128) NOT NULL, 
	description_fa TEXT NOT NULL, 
	description_en TEXT NOT NULL, 
	is_system BOOLEAN DEFAULT false NOT NULL, 
	is_super_admin BOOLEAN DEFAULT false NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_admin_roles PRIMARY KEY (id), 
	CONSTRAINT uq_admin_roles_code UNIQUE (code)
)""",
    r"""CREATE TABLE permissions (
	code VARCHAR(128) NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	name_fa VARCHAR(255) NOT NULL, 
	name_en VARCHAR(255) NOT NULL, 
	description_fa TEXT NOT NULL, 
	description_en TEXT NOT NULL, 
	risk_level VARCHAR(16) NOT NULL, 
	super_admin_only BOOLEAN DEFAULT false NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_permissions PRIMARY KEY (id), 
	CONSTRAINT ck_permissions_risk_level CHECK (risk_level IN ('low', 'medium', 'high', 'critical')), 
	CONSTRAINT uq_permissions_code UNIQUE (code)
)""",
    r"""CREATE INDEX ix_permissions_category_code ON permissions (category, code)""",
    r"""CREATE TABLE settings (
	key VARCHAR(128) NOT NULL, 
	display_name_fa VARCHAR(255) NOT NULL, 
	display_name_en VARCHAR(255) NOT NULL, 
	description_fa TEXT NOT NULL, 
	description_en TEXT NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	value_type VARCHAR(24) NOT NULL, 
	unit VARCHAR(32), 
	value JSONB NOT NULL, 
	default_value JSONB NOT NULL, 
	minimum NUMERIC(30, 6), 
	maximum NUMERIC(30, 6), 
	allowed_values JSONB, 
	sensitive BOOLEAN DEFAULT false NOT NULL, 
	runtime_editable BOOLEAN DEFAULT true NOT NULL, 
	reload_type VARCHAR(24) DEFAULT 'hot_reload' NOT NULL, 
	required_permission VARCHAR(128) NOT NULL, 
	dependencies JSONB DEFAULT '{}'::jsonb NOT NULL, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_settings PRIMARY KEY (id), 
	CONSTRAINT ck_settings_value_type CHECK (value_type IN ('integer', 'decimal', 'boolean', 'string', 'enum', 'duration', 'bytes', 'bitrate', 'percentage', 'list', 'controlled_json')), 
	CONSTRAINT ck_settings_reload_type CHECK (reload_type IN ('hot_reload', 'graceful_reload', 'restart_required')), 
	CONSTRAINT ck_settings_key_format CHECK (key ~ '^[a-z][a-z0-9_.-]{1,127}$'), 
	CONSTRAINT ck_settings_valid_numeric_range CHECK (minimum IS NULL OR maximum IS NULL OR minimum <= maximum), 
	CONSTRAINT ck_settings_positive_version CHECK (version > 0), 
	CONSTRAINT uq_settings_key UNIQUE (key)
)""",
    r"""CREATE INDEX ix_settings_category_key ON settings (category, key)""",
    r"""CREATE TABLE storage_statistics (
	scope VARCHAR(64) NOT NULL, 
	total_bytes BIGINT NOT NULL, 
	used_bytes BIGINT NOT NULL, 
	free_bytes BIGINT NOT NULL, 
	incoming_bytes BIGINT DEFAULT '0' NOT NULL, 
	media_cache_bytes BIGINT DEFAULT '0' NOT NULL, 
	file_count BIGINT DEFAULT '0' NOT NULL, 
	pressure_state VARCHAR(16) DEFAULT 'normal' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_storage_statistics PRIMARY KEY (id), 
	CONSTRAINT ck_storage_statistics_nonnegative_total CHECK (total_bytes >= 0), 
	CONSTRAINT ck_storage_statistics_nonnegative_used CHECK (used_bytes >= 0), 
	CONSTRAINT ck_storage_statistics_nonnegative_free CHECK (free_bytes >= 0), 
	CONSTRAINT ck_storage_statistics_valid_capacity CHECK (used_bytes + free_bytes <= total_bytes)
)""",
    r"""CREATE INDEX ix_storage_statistics_scope_created ON storage_statistics (scope, created_at)""",
    r"""CREATE TABLE terms_versions (
	version VARCHAR(64) NOT NULL, 
	body_fa TEXT NOT NULL, 
	body_en TEXT NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_active BOOLEAN DEFAULT false NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_terms_versions PRIMARY KEY (id), 
	CONSTRAINT uq_terms_versions_version UNIQUE (version)
)""",
    r"""CREATE TABLE privacy_versions (
	version VARCHAR(64) NOT NULL, 
	body_fa TEXT NOT NULL, 
	body_en TEXT NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_active BOOLEAN DEFAULT false NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_privacy_versions PRIMARY KEY (id), 
	CONSTRAINT uq_privacy_versions_version UNIQUE (version)
)""",
    r"""CREATE TABLE subscription_plans (
	code VARCHAR(64) NOT NULL, 
	name_fa VARCHAR(128) NOT NULL, 
	name_en VARCHAR(128) NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	is_system BOOLEAN DEFAULT false NOT NULL, 
	max_file_size BIGINT NOT NULL, 
	quota_bytes BIGINT, 
	quota_window_seconds INTEGER, 
	hourly_quota BIGINT, 
	daily_quota BIGINT, 
	weekly_quota BIGINT, 
	max_files_per_window INTEGER, 
	concurrent_jobs INTEGER DEFAULT '1' NOT NULL, 
	concurrent_downloads INTEGER DEFAULT '1' NOT NULL, 
	concurrent_streams INTEGER DEFAULT '1' NOT NULL, 
	storage_quota BIGINT, 
	active_link_limit INTEGER DEFAULT '10' NOT NULL, 
	download_connection_limit INTEGER DEFAULT '2' NOT NULL, 
	stream_connection_limit INTEGER DEFAULT '2' NOT NULL, 
	allowed_ips_per_session INTEGER DEFAULT '2' NOT NULL, 
	resume_limit INTEGER DEFAULT '20' NOT NULL, 
	range_request_limit INTEGER DEFAULT '1000' NOT NULL, 
	download_rate BIGINT, 
	stream_rate BIGINT, 
	retention_seconds INTEGER NOT NULL, 
	public_retention_seconds INTEGER, 
	queue_priority INTEGER DEFAULT '0' NOT NULL, 
	media_priority INTEGER DEFAULT '0' NOT NULL, 
	max_stream_quality VARCHAR(32) DEFAULT 'original' NOT NULL, 
	public_share_limit INTEGER DEFAULT '0' NOT NULL, 
	support_ticket_limit INTEGER DEFAULT '1' NOT NULL, 
	external_url_enabled BOOLEAN DEFAULT true NOT NULL, 
	streaming_enabled BOOLEAN DEFAULT true NOT NULL, 
	public_share_enabled BOOLEAN DEFAULT false NOT NULL, 
	permanent_link_enabled BOOLEAN DEFAULT false NOT NULL, 
	one_time_link_enabled BOOLEAN DEFAULT true NOT NULL, 
	password_link_enabled BOOLEAN DEFAULT false NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_subscription_plans PRIMARY KEY (id), 
	CONSTRAINT ck_subscription_plans_positive_max_file_size CHECK (max_file_size > 0), 
	CONSTRAINT ck_subscription_plans_positive_concurrent_jobs CHECK (concurrent_jobs > 0), 
	CONSTRAINT ck_subscription_plans_positive_concurrent_downloads CHECK (concurrent_downloads > 0), 
	CONSTRAINT ck_subscription_plans_positive_concurrent_streams CHECK (concurrent_streams > 0), 
	CONSTRAINT ck_subscription_plans_positive_retention_seconds CHECK (retention_seconds > 0), 
	CONSTRAINT ck_subscription_plans_nonnegative_queue_priority CHECK (queue_priority >= 0), 
	CONSTRAINT uq_subscription_plans_code UNIQUE (code)
)""",
    r"""CREATE TABLE outbox_events (
	aggregate_type VARCHAR(48) NOT NULL, 
	aggregate_id UUID NOT NULL, 
	event_type VARCHAR(96) NOT NULL, 
	stream_name VARCHAR(128) NOT NULL, 
	payload JSONB NOT NULL, 
	deduplication_key VARCHAR(192) NOT NULL, 
	state VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	redis_message_id VARCHAR(64), 
	last_error TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_outbox_events PRIMARY KEY (id), 
	CONSTRAINT ck_outbox_events_state CHECK (state IN ('pending', 'published', 'failed')), 
	CONSTRAINT ck_outbox_events_nonnegative_attempt_count CHECK (attempt_count >= 0), 
	CONSTRAINT uq_outbox_events_deduplication_key UNIQUE (deduplication_key)
)""",
    r"""CREATE INDEX ix_outbox_events_publish ON outbox_events (available_at, created_at) WHERE state IN ('pending', 'failed')""",
    r"""CREATE TABLE application_instances (
	installation_id VARCHAR(64) NOT NULL, 
	instance_name VARCHAR(128) NOT NULL, 
	service_type VARCHAR(48) NOT NULL, 
	version VARCHAR(64) NOT NULL, 
	status VARCHAR(16) DEFAULT 'starting' NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_application_instances PRIMARY KEY (id), 
	CONSTRAINT ck_application_instances_status CHECK (status IN ('starting', 'ready', 'draining', 'stopped', 'failed')), 
	CONSTRAINT uq_application_instances_identity UNIQUE (installation_id, instance_name)
)""",
    r"""CREATE INDEX ix_application_instances_heartbeat ON application_instances (status, last_heartbeat_at)""",
    r"""CREATE TABLE telegram_api_capabilities (
	installation_id VARCHAR(64) NOT NULL, 
	api_mode VARCHAR(16) NOT NULL, 
	endpoint_fingerprint BYTEA NOT NULL, 
	server_version VARCHAR(64), 
	image_digest VARCHAR(128), 
	upload_limit_bytes BIGINT NOT NULL, 
	unlimited_download BOOLEAN DEFAULT false NOT NULL, 
	absolute_file_paths BOOLEAN DEFAULT false NOT NULL, 
	verification_status VARCHAR(24) NOT NULL, 
	verification_source VARCHAR(255) NOT NULL, 
	verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_telegram_api_capabilities PRIMARY KEY (id), 
	CONSTRAINT ck_telegram_api_capabilities_positive_upload_limit CHECK (upload_limit_bytes > 0), 
	CONSTRAINT uq_telegram_capabilities_endpoint UNIQUE (installation_id, endpoint_fingerprint)
)""",
    r"""CREATE INDEX ix_telegram_capabilities_active ON telegram_api_capabilities (is_active, verified_at)""",
    r"""CREATE TABLE webhook_updates (
	telegram_update_id BIGINT NOT NULL, 
	update_type VARCHAR(48) NOT NULL, 
	payload_hash BYTEA NOT NULL, 
	status VARCHAR(24) DEFAULT 'received' NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(96), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_webhook_updates PRIMARY KEY (id), 
	CONSTRAINT ck_webhook_updates_nonnegative_update_id CHECK (telegram_update_id >= 0), 
	CONSTRAINT uq_webhook_updates_telegram_update_id UNIQUE (telegram_update_id)
)""",
    r"""CREATE INDEX ix_webhook_updates_status_received ON webhook_updates (status, received_at)""",
    r"""CREATE TABLE forced_join_channels (
	telegram_chat_id BIGINT NOT NULL, 
	username VARCHAR(64), 
	join_url VARCHAR(2048) NOT NULL, 
	title_fa VARCHAR(255) NOT NULL, 
	title_en VARCHAR(255) NOT NULL, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	display_order INTEGER DEFAULT '0' NOT NULL, 
	membership_cache_seconds INTEGER DEFAULT '300' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_forced_join_channels PRIMARY KEY (id), 
	CONSTRAINT ck_forced_join_channels_nonzero_chat_id CHECK (telegram_chat_id <> 0), 
	CONSTRAINT uq_forced_join_channels_telegram_chat_id UNIQUE (telegram_chat_id)
)""",
    r"""CREATE INDEX ix_forced_join_channels_enabled_order ON forced_join_channels (is_enabled, display_order)""",
    r"""CREATE TABLE advertisements (
	name VARCHAR(128) NOT NULL, 
	text_fa TEXT NOT NULL, 
	text_en TEXT NOT NULL, 
	target_url VARCHAR(2048) NOT NULL, 
	plan_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	click_tracking_enabled BOOLEAN DEFAULT false NOT NULL, 
	click_count BIGINT DEFAULT '0' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_advertisements PRIMARY KEY (id), 
	CONSTRAINT ck_advertisements_valid_period CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT ck_advertisements_nonnegative_click_count CHECK (click_count >= 0), 
	CONSTRAINT uq_advertisements_name UNIQUE (name)
)""",
    r"""CREATE INDEX ix_advertisements_active_period ON advertisements (is_enabled, starts_at, ends_at)""",
    r"""CREATE TABLE public_categories (
	code VARCHAR(64) NOT NULL, 
	title_fa VARCHAR(255) NOT NULL, 
	title_en VARCHAR(255) NOT NULL, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	display_order INTEGER DEFAULT '0' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_public_categories PRIMARY KEY (id), 
	CONSTRAINT uq_public_categories_code UNIQUE (code)
)""",
    r"""CREATE TABLE role_permissions (
	role_id UUID NOT NULL, 
	permission_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_role_permissions PRIMARY KEY (id), 
	CONSTRAINT uq_role_permissions_pair UNIQUE (role_id, permission_id), 
	CONSTRAINT fk_role_permissions_role_id_admin_roles FOREIGN KEY(role_id) REFERENCES admin_roles (id) ON DELETE CASCADE, 
	CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)""",
    r"""CREATE TABLE users (
	telegram_user_id BIGINT NOT NULL, 
	username VARCHAR(64), 
	first_name VARCHAR(255), 
	last_name VARCHAR(255), 
	language_code VARCHAR(2) DEFAULT 'fa' NOT NULL, 
	timezone VARCHAR(64) DEFAULT 'UTC' NOT NULL, 
	preferred_date_format VARCHAR(32) DEFAULT 'locale' NOT NULL, 
	preferred_digits VARCHAR(16) DEFAULT 'locale' NOT NULL, 
	status VARCHAR(24) DEFAULT 'active' NOT NULL, 
	terms_version_accepted UUID, 
	privacy_version_accepted UUID, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT ck_users_language_code CHECK (language_code IN ('fa', 'en')), 
	CONSTRAINT ck_users_status CHECK (status IN ('active', 'restricted', 'banned', 'deleted')), 
	CONSTRAINT ck_users_positive_telegram_user_id CHECK (telegram_user_id > 0), 
	CONSTRAINT uq_users_telegram_user_id UNIQUE (telegram_user_id), 
	CONSTRAINT fk_users_terms_version_accepted_terms_versions FOREIGN KEY(terms_version_accepted) REFERENCES terms_versions (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_users_privacy_version_accepted_privacy_versions FOREIGN KEY(privacy_version_accepted) REFERENCES privacy_versions (id) ON DELETE RESTRICT
)""",
    r"""CREATE INDEX ix_users_status_created_at ON users (status, created_at)""",
    r"""CREATE TABLE worker_leases (
	resource_type VARCHAR(48) NOT NULL, 
	resource_id UUID NOT NULL, 
	instance_id UUID NOT NULL, 
	lease_token_hash BYTEA NOT NULL, 
	generation INTEGER NOT NULL, 
	acquired_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_worker_leases PRIMARY KEY (id), 
	CONSTRAINT ck_worker_leases_valid_lease_period CHECK (lease_expires_at > acquired_at), 
	CONSTRAINT uq_worker_leases_resource UNIQUE (resource_type, resource_id), 
	CONSTRAINT fk_worker_leases_instance_id_application_instances FOREIGN KEY(instance_id) REFERENCES application_instances (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_worker_leases_expiry ON worker_leases (lease_expires_at)""",
    r"""CREATE TABLE admins (
	user_id UUID NOT NULL, 
	role_id UUID NOT NULL, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	language_code VARCHAR(2) DEFAULT 'fa' NOT NULL, 
	timezone VARCHAR(64) DEFAULT 'UTC' NOT NULL, 
	preferred_date_format VARCHAR(32) DEFAULT 'locale' NOT NULL, 
	preferred_digits VARCHAR(16) DEFAULT 'locale' NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	max_permission_uses BIGINT, 
	permission_use_count BIGINT DEFAULT '0' NOT NULL, 
	added_by_admin_id UUID, 
	suspended_at TIMESTAMP WITH TIME ZONE, 
	suspension_reason TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admins PRIMARY KEY (id), 
	CONSTRAINT ck_admins_status CHECK (status IN ('active', 'suspended', 'expired', 'removed')), 
	CONSTRAINT ck_admins_language_code CHECK (language_code IN ('fa', 'en')), 
	CONSTRAINT ck_admins_valid_period CHECK (ends_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT ck_admins_positive_max_uses CHECK (max_permission_uses IS NULL OR max_permission_uses > 0), 
	CONSTRAINT ck_admins_nonnegative_use_count CHECK (permission_use_count >= 0), 
	CONSTRAINT uq_admins_user_id UNIQUE (user_id), 
	CONSTRAINT fk_admins_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_admins_role_id_admin_roles FOREIGN KEY(role_id) REFERENCES admin_roles (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_admins_added_by_admin_id_admins FOREIGN KEY(added_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_admins_status_expiry ON admins (status, ends_at)""",
    r"""CREATE TABLE user_consents (
	user_id UUID NOT NULL, 
	terms_version_id UUID NOT NULL, 
	privacy_version_id UUID NOT NULL, 
	source VARCHAR(32) DEFAULT 'telegram' NOT NULL, 
	telegram_update_id BIGINT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_user_consents PRIMARY KEY (id), 
	CONSTRAINT uq_user_consents_versions UNIQUE (user_id, terms_version_id, privacy_version_id), 
	CONSTRAINT fk_user_consents_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_consents_terms_version_id_terms_versions FOREIGN KEY(terms_version_id) REFERENCES terms_versions (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_user_consents_privacy_version_id_privacy_versions FOREIGN KEY(privacy_version_id) REFERENCES privacy_versions (id) ON DELETE RESTRICT
)""",
    r"""CREATE INDEX ix_user_consents_user_created_at ON user_consents (user_id, created_at)""",
    r"""CREATE TABLE quota_buckets (
	user_id UUID NOT NULL, 
	dimension VARCHAR(32) NOT NULL, 
	window_kind VARCHAR(16) NOT NULL, 
	window_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	window_end TIMESTAMP WITH TIME ZONE NOT NULL, 
	quota_limit BIGINT, 
	committed_amount BIGINT DEFAULT '0' NOT NULL, 
	reserved_amount BIGINT DEFAULT '0' NOT NULL, 
	row_version INTEGER DEFAULT '1' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_quota_buckets PRIMARY KEY (id), 
	CONSTRAINT ck_quota_buckets_dimension CHECK (dimension IN ('ingress_bytes', 'egress_bytes', 'storage_bytes', 'file_count', 'job_count', 'download_count', 'stream_count')), 
	CONSTRAINT ck_quota_buckets_window_kind CHECK (window_kind IN ('hourly', 'multi_hour', 'daily', 'weekly', 'lifetime')), 
	CONSTRAINT ck_quota_buckets_valid_window CHECK (window_end > window_start), 
	CONSTRAINT ck_quota_buckets_nonnegative_limit CHECK (quota_limit IS NULL OR quota_limit >= 0), 
	CONSTRAINT ck_quota_buckets_nonnegative_committed CHECK (committed_amount >= 0), 
	CONSTRAINT ck_quota_buckets_nonnegative_reserved CHECK (reserved_amount >= 0), 
	CONSTRAINT ck_quota_buckets_within_quota_limit CHECK (quota_limit IS NULL OR committed_amount + reserved_amount <= quota_limit), 
	CONSTRAINT ck_quota_buckets_positive_row_version CHECK (row_version > 0), 
	CONSTRAINT uq_quota_buckets_identity UNIQUE (user_id, dimension, window_kind, window_start, window_end), 
	CONSTRAINT fk_quota_buckets_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_quota_buckets_expiry ON quota_buckets (window_end)""",
    r"""CREATE TABLE jobs (
	user_id UUID NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	job_type VARCHAR(48) NOT NULL, 
	status VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	queue_class VARCHAR(16) DEFAULT 'normal' NOT NULL, 
	base_priority INTEGER DEFAULT '0' NOT NULL, 
	effective_priority INTEGER DEFAULT '0' NOT NULL, 
	priority_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL, 
	policy_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL, 
	payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
	result JSONB DEFAULT '{}'::jsonb NOT NULL, 
	idempotency_key VARCHAR(160) NOT NULL, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	max_attempts INTEGER DEFAULT '3' NOT NULL, 
	dispatch_generation INTEGER DEFAULT '0' NOT NULL, 
	assigned_instance_id UUID, 
	lease_token_hash BYTEA, 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	queued_at TIMESTAMP WITH TIME ZONE, 
	dispatched_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	next_retry_at TIMESTAMP WITH TIME ZONE, 
	progress_stage VARCHAR(32), 
	progress_percent INTEGER DEFAULT '0' NOT NULL, 
	bytes_transferred BIGINT DEFAULT '0' NOT NULL, 
	total_bytes BIGINT, 
	cancellation_requested_at TIMESTAMP WITH TIME ZONE, 
	cancellation_reason TEXT, 
	last_error_code VARCHAR(96), 
	last_error_detail TEXT, 
	row_version INTEGER DEFAULT '1' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_jobs PRIMARY KEY (id), 
	CONSTRAINT ck_jobs_source CHECK (source IN ('telegram', 'external_url', 'internal')), 
	CONSTRAINT ck_jobs_status CHECK (status IN ('pending', 'quota_reserved', 'queued', 'dispatched', 'downloading', 'receiving', 'scanning', 'processing', 'remuxing', 'transcoding', 'uploading', 'generating_link', 'completed', 'failed', 'cancelled', 'expired', 'cancelled_by_migration', 'dead_letter')), 
	CONSTRAINT ck_jobs_nonnegative_base_priority CHECK (base_priority >= 0), 
	CONSTRAINT ck_jobs_nonnegative_effective_priority CHECK (effective_priority >= 0), 
	CONSTRAINT ck_jobs_nonnegative_attempt_count CHECK (attempt_count >= 0), 
	CONSTRAINT ck_jobs_positive_max_attempts CHECK (max_attempts > 0), 
	CONSTRAINT ck_jobs_attempt_within_limit CHECK (attempt_count <= max_attempts), 
	CONSTRAINT ck_jobs_nonnegative_dispatch_generation CHECK (dispatch_generation >= 0), 
	CONSTRAINT ck_jobs_valid_progress CHECK (progress_percent >= 0 AND progress_percent <= 100), 
	CONSTRAINT ck_jobs_nonnegative_bytes_transferred CHECK (bytes_transferred >= 0), 
	CONSTRAINT ck_jobs_nonnegative_total_bytes CHECK (total_bytes IS NULL OR total_bytes >= 0), 
	CONSTRAINT uq_jobs_idempotency_key UNIQUE (idempotency_key), 
	CONSTRAINT fk_jobs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_jobs_assigned_instance_id_application_instances FOREIGN KEY(assigned_instance_id) REFERENCES application_instances (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_jobs_user_status ON jobs (user_id, status)""",
    r"""CREATE INDEX ix_jobs_retry ON jobs (status, next_retry_at)""",
    r"""CREATE INDEX ix_jobs_stale_dispatch ON jobs (status, lease_expires_at)""",
    r"""CREATE INDEX ix_jobs_dispatch_eligible ON jobs (job_type, queue_class, effective_priority, queued_at) WHERE status = 'queued'""",
    r"""CREATE TABLE admin_permission_overrides (
	admin_id UUID NOT NULL, 
	permission_id UUID NOT NULL, 
	effect VARCHAR(8) NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	reason TEXT NOT NULL, 
	granted_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admin_permission_overrides PRIMARY KEY (id), 
	CONSTRAINT ck_admin_permission_overrides_effect CHECK (effect IN ('allow', 'deny')), 
	CONSTRAINT ck_admin_permission_overrides_valid_period CHECK (ends_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT uq_admin_permission_overrides_pair UNIQUE (admin_id, permission_id), 
	CONSTRAINT fk_admin_permission_overrides_admin_id_admins FOREIGN KEY(admin_id) REFERENCES admins (id) ON DELETE CASCADE, 
	CONSTRAINT fk_admin_permission_overrides_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_admin_permission_overrides_granted_by_admin_id_admins FOREIGN KEY(granted_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_admin_permission_overrides_active ON admin_permission_overrides (admin_id, ends_at)""",
    r"""CREATE TABLE admin_scopes (
	admin_id UUID NOT NULL, 
	scope_type VARCHAR(64) NOT NULL, 
	constraints_json JSONB NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admin_scopes PRIMARY KEY (id), 
	CONSTRAINT ck_admin_scopes_valid_period CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT uq_admin_scopes_type UNIQUE (admin_id, scope_type), 
	CONSTRAINT fk_admin_scopes_admin_id_admins FOREIGN KEY(admin_id) REFERENCES admins (id) ON DELETE CASCADE
)""",
    r"""CREATE TABLE admin_sessions (
	admin_id UUID NOT NULL, 
	session_token_hash BYTEA NOT NULL, 
	source_ip_hash BYTEA, 
	user_agent_hash BYTEA, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoke_reason VARCHAR(128), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admin_sessions PRIMARY KEY (id), 
	CONSTRAINT ck_admin_sessions_token_hash_minimum CHECK (octet_length(session_token_hash) >= 32), 
	CONSTRAINT ck_admin_sessions_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT uq_admin_sessions_token_hash UNIQUE (session_token_hash), 
	CONSTRAINT fk_admin_sessions_admin_id_admins FOREIGN KEY(admin_id) REFERENCES admins (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_admin_sessions_admin_expiry ON admin_sessions (admin_id, expires_at, revoked_at)""",
    r"""CREATE TABLE admin_confirmations (
	admin_id UUID NOT NULL, 
	action_key VARCHAR(192) NOT NULL, 
	action VARCHAR(128) NOT NULL, 
	target_type VARCHAR(64) NOT NULL, 
	target_id VARCHAR(128), 
	payload_hash BYTEA NOT NULL, 
	token_hash BYTEA NOT NULL, 
	reason TEXT NOT NULL, 
	required_approvals INTEGER DEFAULT '1' NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admin_confirmations PRIMARY KEY (id), 
	CONSTRAINT ck_admin_confirmations_status CHECK (status IN ('pending', 'consumed', 'expired', 'cancelled')), 
	CONSTRAINT ck_admin_confirmations_token_hash_minimum CHECK (octet_length(token_hash) >= 32), 
	CONSTRAINT ck_admin_confirmations_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT ck_admin_confirmations_positive_required_approvals CHECK (required_approvals > 0), 
	CONSTRAINT uq_admin_confirmations_token_hash UNIQUE (token_hash), 
	CONSTRAINT uq_admin_confirmations_action_key UNIQUE (action_key), 
	CONSTRAINT fk_admin_confirmations_admin_id_admins FOREIGN KEY(admin_id) REFERENCES admins (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_admin_confirmations_admin_status ON admin_confirmations (admin_id, status, expires_at)""",
    r"""CREATE TABLE admin_audit_logs (
	admin_id UUID, 
	action VARCHAR(128) NOT NULL, 
	target_type VARCHAR(64) NOT NULL, 
	target_id VARCHAR(128), 
	permission VARCHAR(128), 
	old_value JSONB, 
	new_value JSONB, 
	reason TEXT, 
	success BOOLEAN NOT NULL, 
	error_code VARCHAR(96), 
	telegram_update_id BIGINT, 
	request_id VARCHAR(128), 
	previous_hash BYTEA, 
	record_hash BYTEA, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admin_audit_logs PRIMARY KEY (id), 
	CONSTRAINT fk_admin_audit_logs_admin_id_admins FOREIGN KEY(admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_admin_audit_logs_admin_created ON admin_audit_logs (admin_id, created_at)""",
    r"""CREATE INDEX ix_admin_audit_logs_target_created ON admin_audit_logs (target_type, target_id, created_at)""",
    r"""CREATE INDEX ix_admin_audit_logs_action_created ON admin_audit_logs (action, created_at)""",
    r"""CREATE TABLE settings_history (
	setting_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	old_value JSONB NOT NULL, 
	new_value JSONB NOT NULL, 
	changed_by_admin_id UUID, 
	reason TEXT NOT NULL, 
	rollback_of_history_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_settings_history PRIMARY KEY (id), 
	CONSTRAINT ck_settings_history_positive_version CHECK (version > 0), 
	CONSTRAINT uq_settings_history_version UNIQUE (setting_id, version), 
	CONSTRAINT fk_settings_history_setting_id_settings FOREIGN KEY(setting_id) REFERENCES settings (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_settings_history_changed_by_admin_id_admins FOREIGN KEY(changed_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL, 
	CONSTRAINT fk_settings_history_rollback_of_history_id_settings_history FOREIGN KEY(rollback_of_history_id) REFERENCES settings_history (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_settings_history_setting_created ON settings_history (setting_id, created_at)""",
    r"""CREATE TABLE settings_profiles (
	code VARCHAR(64) NOT NULL, 
	name_fa VARCHAR(128) NOT NULL, 
	name_en VARCHAR(128) NOT NULL, 
	description_fa TEXT NOT NULL, 
	description_en TEXT NOT NULL, 
	values JSONB NOT NULL, 
	is_system BOOLEAN DEFAULT false NOT NULL, 
	created_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_settings_profiles PRIMARY KEY (id), 
	CONSTRAINT uq_settings_profiles_code UNIQUE (code), 
	CONSTRAINT fk_settings_profiles_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE TABLE translation_overrides (
	locale VARCHAR(2) NOT NULL, 
	message_key VARCHAR(192) NOT NULL, 
	value TEXT NOT NULL, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	changed_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_translation_overrides PRIMARY KEY (id), 
	CONSTRAINT ck_translation_overrides_locale CHECK (locale IN ('fa', 'en')), 
	CONSTRAINT ck_translation_overrides_message_key_format CHECK (message_key ~ '^[a-z][a-z0-9_.-]{1,191}$'), 
	CONSTRAINT uq_translation_overrides_key UNIQUE (locale, message_key), 
	CONSTRAINT fk_translation_overrides_changed_by_admin_id_admins FOREIGN KEY(changed_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_translation_overrides_locale_enabled ON translation_overrides (locale, is_enabled)""",
    r"""CREATE TABLE files (
	owner_user_id UUID NOT NULL, 
	created_by_job_id UUID NOT NULL, 
	source_type VARCHAR(24) NOT NULL, 
	status VARCHAR(32) DEFAULT 'incoming' NOT NULL, 
	storage_key VARCHAR(512) NOT NULL, 
	original_filename VARCHAR(1024) NOT NULL, 
	safe_display_filename VARCHAR(1024) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 BYTEA, 
	detected_mime VARCHAR(255) NOT NULL, 
	reported_mime VARCHAR(255), 
	scan_status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	media_metadata JSONB DEFAULT '{}'::jsonb NOT NULL, 
	direct_play_compatible BOOLEAN DEFAULT false NOT NULL, 
	retention_seconds INTEGER NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deletion_started_at TIMESTAMP WITH TIME ZONE, 
	unavailable_reason VARCHAR(96), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_files PRIMARY KEY (id), 
	CONSTRAINT ck_files_status CHECK (status IN ('incoming', 'quarantined', 'available', 'deleting', 'deleted', 'expired', 'unavailable_after_migration')), 
	CONSTRAINT ck_files_scan_status CHECK (scan_status IN ('pending', 'scanning', 'clean', 'infected', 'suspicious', 'failed', 'skipped')), 
	CONSTRAINT ck_files_nonnegative_size CHECK (size_bytes >= 0), 
	CONSTRAINT ck_files_positive_retention CHECK (retention_seconds > 0), 
	CONSTRAINT ck_files_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT ck_files_sha256_length CHECK (sha256 IS NULL OR octet_length(sha256) = 32), 
	CONSTRAINT fk_files_owner_user_id_users FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_files_created_by_job_id UNIQUE (created_by_job_id), 
	CONSTRAINT fk_files_created_by_job_id_jobs FOREIGN KEY(created_by_job_id) REFERENCES jobs (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_files_storage_key UNIQUE (storage_key)
)""",
    r"""CREATE INDEX ix_files_sha256_size ON files (sha256, size_bytes)""",
    r"""CREATE INDEX ix_files_created_by_job ON files (created_by_job_id)""",
    r"""CREATE INDEX ix_files_owner_status ON files (owner_user_id, status)""",
    r"""CREATE INDEX ix_files_expiry ON files (status, expires_at)""",
    r"""CREATE TABLE user_subscriptions (
	user_id UUID NOT NULL, 
	plan_id UUID NOT NULL, 
	fallback_plan_id UUID, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	granted_by_admin_id UUID, 
	grant_reason TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_user_subscriptions PRIMARY KEY (id), 
	CONSTRAINT ck_user_subscriptions_status CHECK (status IN ('scheduled', 'active', 'expired', 'revoked')), 
	CONSTRAINT ck_user_subscriptions_valid_period CHECK (ends_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT fk_user_subscriptions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_subscriptions_plan_id_subscription_plans FOREIGN KEY(plan_id) REFERENCES subscription_plans (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_user_subscriptions_fallback_plan_id_subscription_plans FOREIGN KEY(fallback_plan_id) REFERENCES subscription_plans (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_user_subscriptions_granted_by_admin_id_admins FOREIGN KEY(granted_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE UNIQUE INDEX uq_user_subscriptions_one_active ON user_subscriptions (user_id) WHERE status = 'active'""",
    r"""CREATE INDEX ix_user_subscriptions_expiry ON user_subscriptions (status, ends_at)""",
    r"""CREATE TABLE user_quota_overrides (
	user_id UUID NOT NULL, 
	overrides JSONB DEFAULT '{}'::jsonb NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	granted_by_admin_id UUID, 
	reason TEXT NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_user_quota_overrides PRIMARY KEY (id), 
	CONSTRAINT ck_user_quota_overrides_valid_period CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT fk_user_quota_overrides_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_quota_overrides_granted_by_admin_id_admins FOREIGN KEY(granted_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_user_quota_overrides_active ON user_quota_overrides (user_id, ends_at)""",
    r"""CREATE TABLE quota_reservations (
	user_id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	quota_bucket_id UUID NOT NULL, 
	dimension VARCHAR(32) NOT NULL, 
	reserved_amount BIGINT NOT NULL, 
	consumed_amount BIGINT DEFAULT '0' NOT NULL, 
	state VARCHAR(16) DEFAULT 'active' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finalized_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_quota_reservations PRIMARY KEY (id), 
	CONSTRAINT ck_quota_reservations_dimension CHECK (dimension IN ('ingress_bytes', 'egress_bytes', 'storage_bytes', 'file_count', 'job_count', 'download_count', 'stream_count')), 
	CONSTRAINT ck_quota_reservations_state CHECK (state IN ('active', 'committed', 'released', 'expired')), 
	CONSTRAINT ck_quota_reservations_positive_reserved_amount CHECK (reserved_amount > 0), 
	CONSTRAINT ck_quota_reservations_valid_consumed_amount CHECK (consumed_amount >= 0 AND consumed_amount <= reserved_amount), 
	CONSTRAINT ck_quota_reservations_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT fk_quota_reservations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_quota_reservations_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	CONSTRAINT fk_quota_reservations_quota_bucket_id_quota_buckets FOREIGN KEY(quota_bucket_id) REFERENCES quota_buckets (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_quota_reservations_reconcile ON quota_reservations (state, expires_at)""",
    r"""CREATE UNIQUE INDEX uq_quota_reservations_active_job_bucket ON quota_reservations (job_id, quota_bucket_id) WHERE state = 'active'""",
    r"""CREATE INDEX ix_quota_reservations_user_state ON quota_reservations (user_id, state)""",
    r"""CREATE TABLE bans (
	user_id UUID NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	reason_code VARCHAR(64) NOT NULL, 
	public_reason_fa TEXT NOT NULL, 
	public_reason_en TEXT NOT NULL, 
	internal_note TEXT, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_by_admin_id UUID, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoked_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_bans PRIMARY KEY (id), 
	CONSTRAINT ck_bans_valid_period CHECK (expires_at IS NULL OR expires_at > starts_at), 
	CONSTRAINT fk_bans_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_bans_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL, 
	CONSTRAINT fk_bans_revoked_by_admin_id_admins FOREIGN KEY(revoked_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_bans_active_user ON bans (user_id, revoked_at, expires_at)""",
    r"""CREATE TABLE job_attempts (
	job_id UUID NOT NULL, 
	attempt_number INTEGER NOT NULL, 
	dispatch_generation INTEGER NOT NULL, 
	instance_id UUID, 
	status VARCHAR(24) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	checkpoint JSONB DEFAULT '{}'::jsonb NOT NULL, 
	error_code VARCHAR(96), 
	error_detail TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_job_attempts PRIMARY KEY (id), 
	CONSTRAINT ck_job_attempts_positive_attempt_number CHECK (attempt_number > 0), 
	CONSTRAINT uq_job_attempts_number UNIQUE (job_id, attempt_number), 
	CONSTRAINT fk_job_attempts_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	CONSTRAINT fk_job_attempts_instance_id_application_instances FOREIGN KEY(instance_id) REFERENCES application_instances (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_job_attempts_instance ON job_attempts (instance_id, started_at)""",
    r"""CREATE TABLE domain_blocklist (
	domain VARCHAR(253) NOT NULL, 
	include_subdomains BOOLEAN DEFAULT true NOT NULL, 
	reason_code VARCHAR(64) NOT NULL, 
	note TEXT, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	created_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_domain_blocklist PRIMARY KEY (id), 
	CONSTRAINT ck_domain_blocklist_normalized_lowercase_domain CHECK (domain = lower(domain)), 
	CONSTRAINT uq_domain_blocklist_domain UNIQUE (domain), 
	CONSTRAINT fk_domain_blocklist_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_domain_blocklist_enabled ON domain_blocklist (is_enabled, domain)""",
    r"""CREATE TABLE file_hash_blocklist (
	sha256 BYTEA NOT NULL, 
	reason_code VARCHAR(64) NOT NULL, 
	note TEXT, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	created_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_file_hash_blocklist PRIMARY KEY (id), 
	CONSTRAINT ck_file_hash_blocklist_sha256_length CHECK (octet_length(sha256) = 32), 
	CONSTRAINT uq_file_hash_blocklist_sha256 UNIQUE (sha256), 
	CONSTRAINT fk_file_hash_blocklist_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_file_hash_blocklist_enabled ON file_hash_blocklist (is_enabled)""",
    r"""CREATE TABLE backups (
	backup_type VARCHAR(32) NOT NULL, 
	status VARCHAR(16) DEFAULT 'creating' NOT NULL, 
	format_version VARCHAR(32) NOT NULL, 
	application_version VARCHAR(64) NOT NULL, 
	schema_revision VARCHAR(64) NOT NULL, 
	storage_key VARCHAR(512), 
	size_bytes BIGINT, 
	checksum_sha256 BYTEA, 
	encrypted BOOLEAN DEFAULT true NOT NULL, 
	encryption_key_version INTEGER, 
	manifest JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_by_admin_id UUID, 
	verified_at TIMESTAMP WITH TIME ZONE, 
	verification_result VARCHAR(64), 
	failure_reason TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_backups PRIMARY KEY (id), 
	CONSTRAINT ck_backups_status CHECK (status IN ('creating', 'verifying', 'ready', 'failed', 'deleted')), 
	CONSTRAINT ck_backups_nonnegative_size CHECK (size_bytes IS NULL OR size_bytes >= 0), 
	CONSTRAINT ck_backups_checksum_length CHECK (checksum_sha256 IS NULL OR octet_length(checksum_sha256) = 32), 
	CONSTRAINT uq_backups_storage_key UNIQUE (storage_key), 
	CONSTRAINT fk_backups_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_backups_status_created ON backups (status, created_at)""",
    r"""CREATE TABLE backup_destinations (
	name VARCHAR(128) NOT NULL, 
	destination_type VARCHAR(24) NOT NULL, 
	configuration JSONB NOT NULL, 
	secret_reference VARCHAR(255) NOT NULL, 
	is_enabled BOOLEAN DEFAULT true NOT NULL, 
	retention_count INTEGER DEFAULT '7' NOT NULL, 
	created_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_backup_destinations PRIMARY KEY (id), 
	CONSTRAINT uq_backup_destinations_name UNIQUE (name), 
	CONSTRAINT fk_backup_destinations_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE TABLE support_tickets (
	user_id UUID NOT NULL, 
	subject VARCHAR(512) NOT NULL, 
	status VARCHAR(16) DEFAULT 'open' NOT NULL, 
	user_language VARCHAR(2) NOT NULL, 
	assigned_admin_id UUID, 
	last_message_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_support_tickets PRIMARY KEY (id), 
	CONSTRAINT ck_support_tickets_status CHECK (status IN ('open', 'answered', 'closed', 'assigned')), 
	CONSTRAINT ck_support_tickets_user_language CHECK (user_language IN ('fa', 'en')), 
	CONSTRAINT fk_support_tickets_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_support_tickets_assigned_admin_id_admins FOREIGN KEY(assigned_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_support_tickets_assignment ON support_tickets (status, assigned_admin_id, created_at)""",
    r"""CREATE INDEX ix_support_tickets_user ON support_tickets (user_id, created_at)""",
    r"""CREATE TABLE broadcasts (
	created_by_admin_id UUID NOT NULL, 
	status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
	target_language VARCHAR(8) DEFAULT 'all' NOT NULL, 
	target_filter JSONB DEFAULT '{}'::jsonb NOT NULL, 
	payload_fa JSONB, 
	payload_en JSONB, 
	target_count BIGINT DEFAULT '0' NOT NULL, 
	success_count BIGINT DEFAULT '0' NOT NULL, 
	failure_count BIGINT DEFAULT '0' NOT NULL, 
	blocked_count BIGINT DEFAULT '0' NOT NULL, 
	deactivated_count BIGINT DEFAULT '0' NOT NULL, 
	scheduled_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	paused_at TIMESTAMP WITH TIME ZONE, 
	cancelled_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_broadcasts PRIMARY KEY (id), 
	CONSTRAINT ck_broadcasts_status CHECK (status IN ('draft', 'queued', 'running', 'paused', 'completed', 'cancelled', 'failed')), 
	CONSTRAINT ck_broadcasts_target_language CHECK (target_language IN ('fa', 'en', 'all')), 
	CONSTRAINT ck_broadcasts_nonnegative_success_count CHECK (success_count >= 0), 
	CONSTRAINT ck_broadcasts_nonnegative_failure_count CHECK (failure_count >= 0), 
	CONSTRAINT ck_broadcasts_nonnegative_blocked_count CHECK (blocked_count >= 0), 
	CONSTRAINT ck_broadcasts_nonnegative_deactivated_count CHECK (deactivated_count >= 0), 
	CONSTRAINT fk_broadcasts_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE RESTRICT
)""",
    r"""CREATE INDEX ix_broadcasts_worker ON broadcasts (status, scheduled_at, created_at)""",
    r"""CREATE TABLE admin_approvals (
	confirmation_id UUID NOT NULL, 
	approver_admin_id UUID NOT NULL, 
	decision VARCHAR(16) NOT NULL, 
	reason TEXT NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_admin_approvals PRIMARY KEY (id), 
	CONSTRAINT ck_admin_approvals_decision CHECK (decision IN ('approved', 'rejected')), 
	CONSTRAINT uq_admin_approvals_approver UNIQUE (confirmation_id, approver_admin_id), 
	CONSTRAINT fk_admin_approvals_confirmation_id_admin_confirmations FOREIGN KEY(confirmation_id) REFERENCES admin_confirmations (id) ON DELETE CASCADE, 
	CONSTRAINT fk_admin_approvals_approver_admin_id_admins FOREIGN KEY(approver_admin_id) REFERENCES admins (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_admin_approvals_confirmation ON admin_approvals (confirmation_id, created_at)""",
    r"""CREATE TABLE file_references (
	user_id UUID NOT NULL, 
	file_id UUID NOT NULL, 
	source_job_id UUID NOT NULL, 
	display_filename VARCHAR(1024) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_owner BOOLEAN DEFAULT false NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_file_references PRIMARY KEY (id), 
	CONSTRAINT ck_file_references_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT uq_file_references_owner_source UNIQUE (user_id, file_id, source_job_id), 
	CONSTRAINT fk_file_references_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_file_references_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_file_references_source_job_id_jobs FOREIGN KEY(source_job_id) REFERENCES jobs (id) ON DELETE RESTRICT
)""",
    r"""CREATE INDEX ix_file_references_file_active ON file_references (file_id, deleted_at)""",
    r"""CREATE INDEX ix_file_references_user_expiry ON file_references (user_id, expires_at)""",
    r"""CREATE TABLE file_scan_results (
	file_id UUID NOT NULL, 
	scanner VARCHAR(64) NOT NULL, 
	scanner_version VARCHAR(64) NOT NULL, 
	signature_version VARCHAR(64), 
	status VARCHAR(16) NOT NULL, 
	finding_code VARCHAR(128), 
	finding_detail TEXT, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_file_scan_results PRIMARY KEY (id), 
	CONSTRAINT ck_file_scan_results_status CHECK (status IN ('pending', 'scanning', 'clean', 'infected', 'suspicious', 'failed', 'skipped')), 
	CONSTRAINT ck_file_scan_results_valid_scan_period CHECK (finished_at IS NULL OR finished_at >= started_at), 
	CONSTRAINT uq_file_scan_results_run UNIQUE (file_id, scanner, scanner_version), 
	CONSTRAINT fk_file_scan_results_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_file_scan_results_status ON file_scan_results (status, created_at)""",
    r"""CREATE TABLE stream_sessions (
	file_id UUID NOT NULL, 
	user_id UUID, 
	session_id_hash BYTEA NOT NULL, 
	source_ip_hash BYTEA NOT NULL, 
	user_agent_hash BYTEA NOT NULL, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	allowed_quality VARCHAR(32) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	bytes_served BIGINT DEFAULT '0' NOT NULL, 
	active_connections INTEGER DEFAULT '0' NOT NULL, 
	unique_ip_count INTEGER DEFAULT '1' NOT NULL, 
	risk_score INTEGER DEFAULT '0' NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoke_reason VARCHAR(128), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_stream_sessions PRIMARY KEY (id), 
	CONSTRAINT ck_stream_sessions_status CHECK (status IN ('active', 'completed', 'expired', 'revoked', 'blocked')), 
	CONSTRAINT ck_stream_sessions_session_hash_minimum CHECK (octet_length(session_id_hash) >= 32), 
	CONSTRAINT ck_stream_sessions_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT ck_stream_sessions_nonnegative_bytes_served CHECK (bytes_served >= 0), 
	CONSTRAINT ck_stream_sessions_nonnegative_active_connections CHECK (active_connections >= 0), 
	CONSTRAINT ck_stream_sessions_nonnegative_unique_ip_count CHECK (unique_ip_count >= 0), 
	CONSTRAINT uq_stream_sessions_hash UNIQUE (session_id_hash), 
	CONSTRAINT fk_stream_sessions_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stream_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_stream_sessions_file_status ON stream_sessions (file_id, status)""",
    r"""CREATE INDEX ix_stream_sessions_expiry ON stream_sessions (status, expires_at)""",
    r"""CREATE INDEX ix_stream_sessions_user_status ON stream_sessions (user_id, status)""",
    r"""CREATE TABLE media_variants (
	file_id UUID NOT NULL, 
	job_id UUID, 
	kind VARCHAR(16) NOT NULL, 
	quality VARCHAR(32) NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	storage_key VARCHAR(512) NOT NULL, 
	mime_type VARCHAR(255) NOT NULL, 
	size_bytes BIGINT, 
	metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	error_code VARCHAR(96), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_media_variants PRIMARY KEY (id), 
	CONSTRAINT ck_media_variants_kind CHECK (kind IN ('direct', 'remux', 'transcode', 'hls', 'thumbnail')), 
	CONSTRAINT ck_media_variants_status CHECK (status IN ('pending', 'processing', 'ready', 'failed', 'deleting', 'deleted')), 
	CONSTRAINT ck_media_variants_nonnegative_size CHECK (size_bytes IS NULL OR size_bytes >= 0), 
	CONSTRAINT ck_media_variants_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT uq_media_variants_file_kind_quality UNIQUE (file_id, kind, quality), 
	CONSTRAINT fk_media_variants_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_media_variants_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL, 
	CONSTRAINT uq_media_variants_storage_key UNIQUE (storage_key)
)""",
    r"""CREATE INDEX ix_media_variants_expiry ON media_variants (status, expires_at)""",
    r"""CREATE TABLE bandwidth_usage (
	user_id UUID, 
	file_id UUID, 
	token_id UUID, 
	session_type VARCHAR(16) NOT NULL, 
	session_id UUID, 
	purpose VARCHAR(24) NOT NULL, 
	source_ip_hash BYTEA NOT NULL, 
	bytes_sent BIGINT NOT NULL, 
	http_status INTEGER NOT NULL, 
	range_start BIGINT, 
	range_end BIGINT, 
	log_source VARCHAR(64) NOT NULL, 
	log_event_id VARCHAR(160) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_bandwidth_usage PRIMARY KEY (id), 
	CONSTRAINT ck_bandwidth_usage_nonnegative_bytes_sent CHECK (bytes_sent >= 0), 
	CONSTRAINT uq_bandwidth_usage_log_event UNIQUE (log_source, log_event_id), 
	CONSTRAINT fk_bandwidth_usage_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_bandwidth_usage_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_bandwidth_usage_ip_created ON bandwidth_usage (source_ip_hash, created_at)""",
    r"""CREATE INDEX ix_bandwidth_usage_session_created ON bandwidth_usage (session_type, session_id, created_at)""",
    r"""CREATE INDEX ix_bandwidth_usage_user_created ON bandwidth_usage (user_id, created_at)""",
    r"""CREATE INDEX ix_bandwidth_usage_file_created ON bandwidth_usage (file_id, created_at)""",
    r"""CREATE TABLE usage_records (
	user_id UUID NOT NULL, 
	quota_bucket_id UUID, 
	reservation_id UUID, 
	job_id UUID, 
	file_id UUID, 
	session_id UUID, 
	dimension VARCHAR(32) NOT NULL, 
	direction VARCHAR(8) DEFAULT 'debit' NOT NULL, 
	amount BIGINT NOT NULL, 
	idempotency_key VARCHAR(160) NOT NULL, 
	metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_usage_records PRIMARY KEY (id), 
	CONSTRAINT ck_usage_records_dimension CHECK (dimension IN ('ingress_bytes', 'egress_bytes', 'storage_bytes', 'file_count', 'job_count', 'download_count', 'stream_count')), 
	CONSTRAINT ck_usage_records_direction CHECK (direction IN ('debit', 'credit')), 
	CONSTRAINT ck_usage_records_positive_amount CHECK (amount > 0), 
	CONSTRAINT uq_usage_records_idempotency_key UNIQUE (idempotency_key), 
	CONSTRAINT fk_usage_records_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_usage_records_quota_bucket_id_quota_buckets FOREIGN KEY(quota_bucket_id) REFERENCES quota_buckets (id) ON DELETE SET NULL, 
	CONSTRAINT fk_usage_records_reservation_id_quota_reservations FOREIGN KEY(reservation_id) REFERENCES quota_reservations (id) ON DELETE SET NULL, 
	CONSTRAINT fk_usage_records_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_usage_records_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_usage_records_user_created ON usage_records (user_id, created_at)""",
    r"""CREATE INDEX ix_usage_records_session ON usage_records (session_id)""",
    r"""CREATE INDEX ix_usage_records_job ON usage_records (job_id)""",
    r"""CREATE TABLE user_restrictions (
	user_id UUID NOT NULL, 
	restriction_type VARCHAR(64) NOT NULL, 
	state VARCHAR(16) DEFAULT 'active' NOT NULL, 
	reason_code VARCHAR(64) NOT NULL, 
	internal_note TEXT, 
	public_explanation_fa TEXT NOT NULL, 
	public_explanation_en TEXT NOT NULL, 
	parameters JSONB DEFAULT '{}'::jsonb NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	related_file_id UUID, 
	related_job_id UUID, 
	appeal_allowed BOOLEAN DEFAULT true NOT NULL, 
	created_by_admin_id UUID, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoked_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_user_restrictions PRIMARY KEY (id), 
	CONSTRAINT ck_user_restrictions_state CHECK (state IN ('active', 'expired', 'revoked')), 
	CONSTRAINT ck_user_restrictions_valid_period CHECK (expires_at IS NULL OR expires_at > starts_at), 
	CONSTRAINT fk_user_restrictions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_restrictions_related_file_id_files FOREIGN KEY(related_file_id) REFERENCES files (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_restrictions_related_job_id_jobs FOREIGN KEY(related_job_id) REFERENCES jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_restrictions_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_restrictions_revoked_by_admin_id_admins FOREIGN KEY(revoked_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_user_restrictions_effective ON user_restrictions (user_id, state, expires_at)""",
    r"""CREATE TABLE job_events (
	job_id UUID NOT NULL, 
	attempt_id UUID, 
	event_type VARCHAR(64) NOT NULL, 
	from_status VARCHAR(32), 
	to_status VARCHAR(32), 
	actor_type VARCHAR(24) NOT NULL, 
	actor_id UUID, 
	details JSONB DEFAULT '{}'::jsonb NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_job_events PRIMARY KEY (id), 
	CONSTRAINT fk_job_events_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	CONSTRAINT fk_job_events_attempt_id_job_attempts FOREIGN KEY(attempt_id) REFERENCES job_attempts (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_job_events_job_created ON job_events (job_id, created_at)""",
    r"""CREATE TABLE security_events (
	event_type VARCHAR(96) NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	status VARCHAR(24) DEFAULT 'open' NOT NULL, 
	user_id UUID, 
	job_id UUID, 
	file_id UUID, 
	session_type VARCHAR(16), 
	session_id UUID, 
	source_ip_hash BYTEA, 
	fingerprint BYTEA, 
	details JSONB DEFAULT '{}'::jsonb NOT NULL, 
	automatic_action VARCHAR(96), 
	resolved_by_admin_id UUID, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	resolution_note TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_security_events PRIMARY KEY (id), 
	CONSTRAINT ck_security_events_severity CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')), 
	CONSTRAINT ck_security_events_status CHECK (status IN ('open', 'investigating', 'resolved', 'false_positive')), 
	CONSTRAINT fk_security_events_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_security_events_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_security_events_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE SET NULL, 
	CONSTRAINT fk_security_events_resolved_by_admin_id_admins FOREIGN KEY(resolved_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_security_events_fingerprint ON security_events (fingerprint, created_at)""",
    r"""CREATE INDEX ix_security_events_triage ON security_events (status, severity, created_at)""",
    r"""CREATE INDEX ix_security_events_job_created ON security_events (job_id, created_at)""",
    r"""CREATE INDEX ix_security_events_user_created ON security_events (user_id, created_at)""",
    r"""CREATE TABLE restore_history (
	backup_id UUID NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	requested_by_admin_id UUID NOT NULL, 
	reason TEXT NOT NULL, 
	source_schema_revision VARCHAR(64) NOT NULL, 
	target_schema_revision VARCHAR(64) NOT NULL, 
	safety_backup_id UUID, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	failure_reason TEXT, 
	rollback_completed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_restore_history PRIMARY KEY (id), 
	CONSTRAINT ck_restore_history_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'rolled_back')), 
	CONSTRAINT fk_restore_history_backup_id_backups FOREIGN KEY(backup_id) REFERENCES backups (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_restore_history_requested_by_admin_id_admins FOREIGN KEY(requested_by_admin_id) REFERENCES admins (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_restore_history_safety_backup_id_backups FOREIGN KEY(safety_backup_id) REFERENCES backups (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_restore_history_status_created ON restore_history (status, created_at)""",
    r"""CREATE TABLE support_messages (
	ticket_id UUID NOT NULL, 
	sender_type VARCHAR(16) NOT NULL, 
	sender_user_id UUID, 
	sender_admin_id UUID, 
	message_type VARCHAR(24) NOT NULL, 
	body TEXT, 
	telegram_file_id VARCHAR(1024), 
	reply_to_message_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_support_messages PRIMARY KEY (id), 
	CONSTRAINT ck_support_messages_valid_sender CHECK ((sender_type = 'user' AND sender_user_id IS NOT NULL AND sender_admin_id IS NULL) OR (sender_type = 'admin' AND sender_admin_id IS NOT NULL AND sender_user_id IS NULL) OR (sender_type = 'system' AND sender_user_id IS NULL AND sender_admin_id IS NULL)), 
	CONSTRAINT fk_support_messages_ticket_id_support_tickets FOREIGN KEY(ticket_id) REFERENCES support_tickets (id) ON DELETE CASCADE, 
	CONSTRAINT fk_support_messages_sender_user_id_users FOREIGN KEY(sender_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_support_messages_sender_admin_id_admins FOREIGN KEY(sender_admin_id) REFERENCES admins (id) ON DELETE SET NULL, 
	CONSTRAINT fk_support_messages_reply_to_message_id_support_messages FOREIGN KEY(reply_to_message_id) REFERENCES support_messages (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_support_messages_ticket_created ON support_messages (ticket_id, created_at)""",
    r"""CREATE TABLE broadcast_results (
	broadcast_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	language_code VARCHAR(2) NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	telegram_message_id BIGINT, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	next_attempt_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(96), 
	sent_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_broadcast_results PRIMARY KEY (id), 
	CONSTRAINT ck_broadcast_results_status CHECK (status IN ('pending', 'sent', 'failed', 'blocked', 'deactivated', 'skipped')), 
	CONSTRAINT uq_broadcast_results_recipient UNIQUE (broadcast_id, user_id), 
	CONSTRAINT fk_broadcast_results_broadcast_id_broadcasts FOREIGN KEY(broadcast_id) REFERENCES broadcasts (id) ON DELETE CASCADE, 
	CONSTRAINT fk_broadcast_results_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_broadcast_results_resume ON broadcast_results (broadcast_id, status)""",
    r"""CREATE TABLE download_links (
	file_id UUID NOT NULL, 
	file_reference_id UUID NOT NULL, 
	owner_user_id UUID NOT NULL, 
	token_hash BYTEA NOT NULL, 
	key_version INTEGER NOT NULL, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	purpose VARCHAR(24) DEFAULT 'private' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	max_downloads INTEGER, 
	download_count INTEGER DEFAULT '0' NOT NULL, 
	one_time BOOLEAN DEFAULT false NOT NULL, 
	password_hash BYTEA, 
	bound_ip_hash BYTEA, 
	policy JSONB DEFAULT '{}'::jsonb NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoke_reason VARCHAR(128), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_download_links PRIMARY KEY (id), 
	CONSTRAINT ck_download_links_status CHECK (status IN ('active', 'exhausted', 'expired', 'revoked')), 
	CONSTRAINT ck_download_links_token_hash_minimum CHECK (octet_length(token_hash) >= 32), 
	CONSTRAINT ck_download_links_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT ck_download_links_positive_max_downloads CHECK (max_downloads IS NULL OR max_downloads > 0), 
	CONSTRAINT ck_download_links_nonnegative_download_count CHECK (download_count >= 0), 
	CONSTRAINT uq_download_links_token_key UNIQUE (token_hash, key_version), 
	CONSTRAINT fk_download_links_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_download_links_file_reference_id_file_references FOREIGN KEY(file_reference_id) REFERENCES file_references (id) ON DELETE CASCADE, 
	CONSTRAINT fk_download_links_owner_user_id_users FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_download_links_file_status ON download_links (file_id, status)""",
    r"""CREATE INDEX ix_download_links_expiry ON download_links (status, expires_at)""",
    r"""CREATE INDEX ix_download_links_owner_status ON download_links (owner_user_id, status)""",
    r"""CREATE TABLE stream_tokens (
	file_id UUID NOT NULL, 
	stream_session_id UUID, 
	user_id UUID, 
	token_hash BYTEA NOT NULL, 
	nonce_hash BYTEA NOT NULL, 
	key_version INTEGER NOT NULL, 
	purpose VARCHAR(16) DEFAULT 'stream' NOT NULL, 
	allowed_quality VARCHAR(32) NOT NULL, 
	maximum_connections INTEGER NOT NULL, 
	maximum_ips INTEGER NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_stream_tokens PRIMARY KEY (id), 
	CONSTRAINT ck_stream_tokens_purpose CHECK (purpose IN ('download', 'stream', 'hls_segment')), 
	CONSTRAINT ck_stream_tokens_stream_purpose_only CHECK (purpose IN ('stream', 'hls_segment')), 
	CONSTRAINT ck_stream_tokens_token_hash_minimum CHECK (octet_length(token_hash) >= 32), 
	CONSTRAINT ck_stream_tokens_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT ck_stream_tokens_positive_maximum_connections CHECK (maximum_connections > 0), 
	CONSTRAINT ck_stream_tokens_positive_maximum_ips CHECK (maximum_ips > 0), 
	CONSTRAINT uq_stream_tokens_token_key UNIQUE (token_hash, key_version), 
	CONSTRAINT fk_stream_tokens_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stream_tokens_stream_session_id_stream_sessions FOREIGN KEY(stream_session_id) REFERENCES stream_sessions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stream_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_stream_tokens_file_expiry ON stream_tokens (file_id, expires_at)""",
    r"""CREATE INDEX ix_stream_tokens_session ON stream_tokens (stream_session_id)""",
    r"""CREATE TABLE media_segments (
	variant_id UUID NOT NULL, 
	sequence_number INTEGER NOT NULL, 
	storage_key VARCHAR(512) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	duration_ms INTEGER NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_media_segments PRIMARY KEY (id), 
	CONSTRAINT ck_media_segments_nonnegative_sequence CHECK (sequence_number >= 0), 
	CONSTRAINT ck_media_segments_nonnegative_size CHECK (size_bytes >= 0), 
	CONSTRAINT ck_media_segments_positive_duration CHECK (duration_ms > 0), 
	CONSTRAINT uq_media_segments_sequence UNIQUE (variant_id, sequence_number), 
	CONSTRAINT fk_media_segments_variant_id_media_variants FOREIGN KEY(variant_id) REFERENCES media_variants (id) ON DELETE CASCADE, 
	CONSTRAINT uq_media_segments_storage_key UNIQUE (storage_key)
)""",
    r"""CREATE INDEX ix_media_segments_expiry ON media_segments (expires_at)""",
    r"""CREATE TABLE user_strikes (
	user_id UUID NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	score INTEGER NOT NULL, 
	reason_code VARCHAR(64) NOT NULL, 
	evidence JSONB DEFAULT '{}'::jsonb NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	related_file_id UUID, 
	related_job_id UUID, 
	related_security_event_id UUID, 
	created_by_admin_id UUID, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoked_by_admin_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_user_strikes PRIMARY KEY (id), 
	CONSTRAINT ck_user_strikes_positive_score CHECK (score > 0), 
	CONSTRAINT fk_user_strikes_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_strikes_related_file_id_files FOREIGN KEY(related_file_id) REFERENCES files (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_strikes_related_job_id_jobs FOREIGN KEY(related_job_id) REFERENCES jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_strikes_related_security_event_id_security_events FOREIGN KEY(related_security_event_id) REFERENCES security_events (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_strikes_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL, 
	CONSTRAINT fk_user_strikes_revoked_by_admin_id_admins FOREIGN KEY(revoked_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_user_strikes_active ON user_strikes (user_id, revoked_at, expires_at)""",
    r"""CREATE TABLE user_appeals (
	restriction_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	explanation TEXT NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	reviewed_by_admin_id UUID, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	decision_note TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_user_appeals PRIMARY KEY (id), 
	CONSTRAINT ck_user_appeals_status CHECK (status IN ('pending', 'approved', 'reduced', 'rejected', 'withdrawn')), 
	CONSTRAINT fk_user_appeals_restriction_id_user_restrictions FOREIGN KEY(restriction_id) REFERENCES user_restrictions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_appeals_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_appeals_reviewed_by_admin_id_admins FOREIGN KEY(reviewed_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE UNIQUE INDEX uq_user_appeals_one_pending_per_restriction ON user_appeals (restriction_id) WHERE status = 'pending'""",
    r"""CREATE INDEX ix_user_appeals_status_created ON user_appeals (status, created_at)""",
    r"""CREATE TABLE abuse_actions (
	security_event_id UUID, 
	user_id UUID, 
	source_ip_hash BYTEA, 
	token_id UUID, 
	action_type VARCHAR(64) NOT NULL, 
	parameters JSONB DEFAULT '{}'::jsonb NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	created_by VARCHAR(24) NOT NULL, 
	created_by_admin_id UUID, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoke_reason TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_abuse_actions PRIMARY KEY (id), 
	CONSTRAINT ck_abuse_actions_valid_period CHECK (ends_at IS NULL OR ends_at > starts_at), 
	CONSTRAINT fk_abuse_actions_security_event_id_security_events FOREIGN KEY(security_event_id) REFERENCES security_events (id) ON DELETE SET NULL, 
	CONSTRAINT fk_abuse_actions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_abuse_actions_created_by_admin_id_admins FOREIGN KEY(created_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_abuse_actions_ip_active ON abuse_actions (source_ip_hash, revoked_at, ends_at)""",
    r"""CREATE INDEX ix_abuse_actions_user_active ON abuse_actions (user_id, revoked_at, ends_at)""",
    r"""CREATE TABLE public_share_requests (
	user_id UUID NOT NULL, 
	file_reference_id UUID NOT NULL, 
	category_id UUID NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	language_mode VARCHAR(16) DEFAULT 'fa' NOT NULL, 
	title_fa VARCHAR(512), 
	title_en VARCHAR(512), 
	description_fa TEXT, 
	description_en TEXT, 
	tags JSONB DEFAULT '[]'::jsonb NOT NULL, 
	rights_confirmed BOOLEAN NOT NULL, 
	policy_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL, 
	reviewed_by_admin_id UUID, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	review_reason TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_public_share_requests PRIMARY KEY (id), 
	CONSTRAINT ck_public_share_requests_status CHECK (status IN ('pending', 'approved', 'rejected', 'published', 'withdrawn')), 
	CONSTRAINT ck_public_share_requests_language_mode CHECK (language_mode IN ('fa', 'en', 'bilingual')), 
	CONSTRAINT fk_public_share_requests_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_public_share_requests_file_reference_id_file_references FOREIGN KEY(file_reference_id) REFERENCES file_references (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_public_share_requests_category_id_public_categories FOREIGN KEY(category_id) REFERENCES public_categories (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_public_share_requests_reviewed_by_admin_id_admins FOREIGN KEY(reviewed_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_public_share_requests_user ON public_share_requests (user_id, created_at)""",
    r"""CREATE INDEX ix_public_share_requests_review ON public_share_requests (status, created_at)""",
    r"""CREATE TABLE download_sessions (
	download_link_id UUID NOT NULL, 
	file_id UUID NOT NULL, 
	owner_user_id UUID NOT NULL, 
	session_id_hash BYTEA NOT NULL, 
	source_ip_hash BYTEA NOT NULL, 
	user_agent_hash BYTEA NOT NULL, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	bytes_served BIGINT DEFAULT '0' NOT NULL, 
	range_requests INTEGER DEFAULT '0' NOT NULL, 
	resume_count INTEGER DEFAULT '0' NOT NULL, 
	active_connections INTEGER DEFAULT '0' NOT NULL, 
	unique_ip_count INTEGER DEFAULT '1' NOT NULL, 
	risk_score INTEGER DEFAULT '0' NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoke_reason VARCHAR(128), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_download_sessions PRIMARY KEY (id), 
	CONSTRAINT ck_download_sessions_status CHECK (status IN ('active', 'completed', 'expired', 'revoked', 'blocked')), 
	CONSTRAINT ck_download_sessions_session_hash_minimum CHECK (octet_length(session_id_hash) >= 32), 
	CONSTRAINT ck_download_sessions_future_expiry CHECK (expires_at > created_at), 
	CONSTRAINT ck_download_sessions_nonnegative_bytes_served CHECK (bytes_served >= 0), 
	CONSTRAINT ck_download_sessions_nonnegative_range_requests CHECK (range_requests >= 0), 
	CONSTRAINT ck_download_sessions_nonnegative_resume_count CHECK (resume_count >= 0), 
	CONSTRAINT ck_download_sessions_nonnegative_active_connections CHECK (active_connections >= 0), 
	CONSTRAINT ck_download_sessions_nonnegative_unique_ip_count CHECK (unique_ip_count >= 0), 
	CONSTRAINT uq_download_sessions_hash UNIQUE (session_id_hash), 
	CONSTRAINT fk_download_sessions_download_link_id_download_links FOREIGN KEY(download_link_id) REFERENCES download_links (id) ON DELETE CASCADE, 
	CONSTRAINT fk_download_sessions_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_download_sessions_owner_user_id_users FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE
)""",
    r"""CREATE INDEX ix_download_sessions_expiry ON download_sessions (status, expires_at)""",
    r"""CREATE INDEX ix_download_sessions_owner_status ON download_sessions (owner_user_id, status)""",
    r"""CREATE INDEX ix_download_sessions_link_status ON download_sessions (download_link_id, status)""",
    r"""CREATE TABLE public_channel_posts (
	share_request_id UUID NOT NULL, 
	file_id UUID NOT NULL, 
	channel_id BIGINT NOT NULL, 
	telegram_message_id BIGINT NOT NULL, 
	language_mode VARCHAR(16) NOT NULL, 
	published_by_admin_id UUID, 
	published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	disabled_at TIMESTAMP WITH TIME ZONE, 
	removed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_public_channel_posts PRIMARY KEY (id), 
	CONSTRAINT uq_public_channel_posts_message UNIQUE (channel_id, telegram_message_id), 
	CONSTRAINT fk_public_channel_posts_share_request_id_public_share_requests FOREIGN KEY(share_request_id) REFERENCES public_share_requests (id) ON DELETE CASCADE, 
	CONSTRAINT fk_public_channel_posts_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_public_channel_posts_published_by_admin_id_admins FOREIGN KEY(published_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE UNIQUE INDEX uq_public_channel_posts_active_request_channel ON public_channel_posts (share_request_id, channel_id) WHERE removed_at IS NULL""",
    r"""CREATE INDEX ix_public_channel_posts_expiry ON public_channel_posts (expires_at, removed_at)""",
    r"""CREATE TABLE file_reports (
	public_post_id UUID NOT NULL, 
	file_id UUID NOT NULL, 
	reporter_user_id UUID, 
	reason_code VARCHAR(64) NOT NULL, 
	explanation TEXT, 
	status VARCHAR(16) DEFAULT 'open' NOT NULL, 
	reviewed_by_admin_id UUID, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	resolution TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_file_reports PRIMARY KEY (id), 
	CONSTRAINT ck_file_reports_status CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed')), 
	CONSTRAINT uq_file_reports_reporter_post UNIQUE (public_post_id, reporter_user_id), 
	CONSTRAINT fk_file_reports_public_post_id_public_channel_posts FOREIGN KEY(public_post_id) REFERENCES public_channel_posts (id) ON DELETE CASCADE, 
	CONSTRAINT fk_file_reports_file_id_files FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	CONSTRAINT fk_file_reports_reporter_user_id_users FOREIGN KEY(reporter_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_file_reports_reviewed_by_admin_id_admins FOREIGN KEY(reviewed_by_admin_id) REFERENCES admins (id) ON DELETE SET NULL
)""",
    r"""CREATE INDEX ix_file_reports_review ON file_reports (status, created_at)""",
    r"""CREATE FUNCTION set_row_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END;
$$""",
    r"""CREATE TRIGGER trg_abuse_actions_set_updated_at
BEFORE UPDATE ON abuse_actions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admin_approvals_set_updated_at
BEFORE UPDATE ON admin_approvals
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admin_confirmations_set_updated_at
BEFORE UPDATE ON admin_confirmations
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admin_permission_overrides_set_updated_at
BEFORE UPDATE ON admin_permission_overrides
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admin_roles_set_updated_at
BEFORE UPDATE ON admin_roles
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admin_scopes_set_updated_at
BEFORE UPDATE ON admin_scopes
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admin_sessions_set_updated_at
BEFORE UPDATE ON admin_sessions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_admins_set_updated_at
BEFORE UPDATE ON admins
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_advertisements_set_updated_at
BEFORE UPDATE ON advertisements
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_application_instances_set_updated_at
BEFORE UPDATE ON application_instances
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_backup_destinations_set_updated_at
BEFORE UPDATE ON backup_destinations
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_backups_set_updated_at
BEFORE UPDATE ON backups
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_bans_set_updated_at
BEFORE UPDATE ON bans
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_broadcast_results_set_updated_at
BEFORE UPDATE ON broadcast_results
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_broadcasts_set_updated_at
BEFORE UPDATE ON broadcasts
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_domain_blocklist_set_updated_at
BEFORE UPDATE ON domain_blocklist
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_download_links_set_updated_at
BEFORE UPDATE ON download_links
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_download_sessions_set_updated_at
BEFORE UPDATE ON download_sessions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_file_hash_blocklist_set_updated_at
BEFORE UPDATE ON file_hash_blocklist
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_file_references_set_updated_at
BEFORE UPDATE ON file_references
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_file_reports_set_updated_at
BEFORE UPDATE ON file_reports
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_file_scan_results_set_updated_at
BEFORE UPDATE ON file_scan_results
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_files_set_updated_at
BEFORE UPDATE ON files
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_forced_join_channels_set_updated_at
BEFORE UPDATE ON forced_join_channels
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_job_attempts_set_updated_at
BEFORE UPDATE ON job_attempts
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_jobs_set_updated_at
BEFORE UPDATE ON jobs
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_media_segments_set_updated_at
BEFORE UPDATE ON media_segments
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_media_variants_set_updated_at
BEFORE UPDATE ON media_variants
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_outbox_events_set_updated_at
BEFORE UPDATE ON outbox_events
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_permissions_set_updated_at
BEFORE UPDATE ON permissions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_privacy_versions_set_updated_at
BEFORE UPDATE ON privacy_versions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_public_categories_set_updated_at
BEFORE UPDATE ON public_categories
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_public_channel_posts_set_updated_at
BEFORE UPDATE ON public_channel_posts
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_public_share_requests_set_updated_at
BEFORE UPDATE ON public_share_requests
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_quota_buckets_set_updated_at
BEFORE UPDATE ON quota_buckets
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_quota_reservations_set_updated_at
BEFORE UPDATE ON quota_reservations
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_restore_history_set_updated_at
BEFORE UPDATE ON restore_history
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_security_events_set_updated_at
BEFORE UPDATE ON security_events
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_settings_set_updated_at
BEFORE UPDATE ON settings
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_settings_profiles_set_updated_at
BEFORE UPDATE ON settings_profiles
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_stream_sessions_set_updated_at
BEFORE UPDATE ON stream_sessions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_stream_tokens_set_updated_at
BEFORE UPDATE ON stream_tokens
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_subscription_plans_set_updated_at
BEFORE UPDATE ON subscription_plans
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_support_messages_set_updated_at
BEFORE UPDATE ON support_messages
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_support_tickets_set_updated_at
BEFORE UPDATE ON support_tickets
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_telegram_api_capabilities_set_updated_at
BEFORE UPDATE ON telegram_api_capabilities
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_terms_versions_set_updated_at
BEFORE UPDATE ON terms_versions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_translation_overrides_set_updated_at
BEFORE UPDATE ON translation_overrides
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_user_appeals_set_updated_at
BEFORE UPDATE ON user_appeals
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_user_quota_overrides_set_updated_at
BEFORE UPDATE ON user_quota_overrides
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_user_restrictions_set_updated_at
BEFORE UPDATE ON user_restrictions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_user_strikes_set_updated_at
BEFORE UPDATE ON user_strikes
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_user_subscriptions_set_updated_at
BEFORE UPDATE ON user_subscriptions
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_users_set_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_webhook_updates_set_updated_at
BEFORE UPDATE ON webhook_updates
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE TRIGGER trg_worker_leases_set_updated_at
BEFORE UPDATE ON worker_leases
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at()""",
    r"""CREATE FUNCTION validate_job_state_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    allowed boolean := false;
BEGIN
    IF NEW.status = OLD.status THEN RETURN NEW; END IF;
    IF NEW.status = 'cancelled_by_migration'
       AND OLD.status NOT IN ('completed', 'expired', 'cancelled_by_migration', 'dead_letter') THEN
        allowed := true;
    ELSIF OLD.status = 'pending' AND NEW.status IN ('quota_reserved', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'quota_reserved' AND NEW.status IN ('queued', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'queued' AND NEW.status IN ('dispatched', 'cancelled', 'expired') THEN allowed := true;
    ELSIF OLD.status = 'dispatched' AND NEW.status IN (
        'downloading', 'receiving', 'scanning', 'processing', 'uploading', 'failed', 'cancelled', 'dead_letter'
    ) THEN allowed := true;
    ELSIF OLD.status IN ('downloading', 'receiving')
          AND NEW.status IN ('scanning', 'processing', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'scanning'
          AND NEW.status IN ('processing', 'generating_link', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'processing'
          AND NEW.status IN ('remuxing', 'transcoding', 'uploading', 'generating_link', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status IN ('remuxing', 'transcoding')
          AND NEW.status IN ('uploading', 'generating_link', 'completed', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'uploading'
          AND NEW.status IN ('generating_link', 'completed', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'generating_link'
          AND NEW.status IN ('completed', 'failed', 'cancelled') THEN allowed := true;
    ELSIF OLD.status = 'failed' AND NEW.status IN ('queued', 'dead_letter', 'expired') THEN allowed := true;
    ELSIF OLD.status IN ('completed', 'cancelled') AND NEW.status = 'expired' THEN allowed := true;
    END IF;
    IF NOT allowed THEN
        RAISE EXCEPTION 'invalid job state transition: % -> %', OLD.status, NEW.status USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$""",
    r"""CREATE TRIGGER trg_jobs_validate_state_transition
BEFORE UPDATE OF status ON jobs
FOR EACH ROW EXECUTE FUNCTION validate_job_state_transition()""",
    r"""CREATE FUNCTION prevent_immutable_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$""",
    r"""CREATE TRIGGER trg_usage_records_immutable
BEFORE UPDATE OR DELETE ON usage_records
FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation()""",
    r"""CREATE TRIGGER trg_job_events_immutable
BEFORE UPDATE OR DELETE ON job_events
FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation()""",
    r"""CREATE TRIGGER trg_admin_audit_logs_immutable
BEFORE UPDATE OR DELETE ON admin_audit_logs
FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation()""",
    r"""CREATE TRIGGER trg_settings_history_immutable
BEFORE UPDATE OR DELETE ON settings_history
FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation()""",
    r"""CREATE FUNCTION protect_last_super_admin() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    old_was_active_super boolean;
    replacement_count bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('mdlbot:last_super_admin', 0));
    SELECT (r.is_super_admin AND OLD.status = 'active'
            AND (OLD.ends_at IS NULL OR OLD.ends_at > statement_timestamp()))
      INTO old_was_active_super
      FROM admin_roles r WHERE r.id = OLD.role_id;
    IF NOT coalesce(old_was_active_super, false) THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' OR NEW.status <> 'active' OR NEW.role_id <> OLD.role_id
       OR (NEW.ends_at IS NOT NULL AND NEW.ends_at <= statement_timestamp()) THEN
        SELECT count(*) INTO replacement_count
          FROM admins a JOIN admin_roles r ON r.id = a.role_id
         WHERE a.id <> OLD.id AND a.status = 'active'
           AND (a.ends_at IS NULL OR a.ends_at > statement_timestamp()) AND r.is_super_admin;
        IF replacement_count = 0 THEN
            RAISE EXCEPTION 'cannot remove or deactivate the last active Super Admin' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$""",
    r"""CREATE TRIGGER trg_admins_protect_last_super_admin
BEFORE UPDATE OF status, role_id, ends_at OR DELETE ON admins
FOR EACH ROW EXECUTE FUNCTION protect_last_super_admin()""",
    r"""CREATE FUNCTION protect_system_admin_role() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_system AND (
        TG_OP = 'DELETE' OR NEW.code <> OLD.code
        OR NEW.is_system IS DISTINCT FROM OLD.is_system
        OR NEW.is_super_admin IS DISTINCT FROM OLD.is_super_admin
    ) THEN
        RAISE EXCEPTION 'system admin role identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$""",
    r"""CREATE TRIGGER trg_admin_roles_protect_system_identity
BEFORE UPDATE OR DELETE ON admin_roles
FOR EACH ROW EXECUTE FUNCTION protect_system_admin_role()""",
    r"""CREATE FUNCTION enforce_approval_separation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    requester uuid;
    approvals_needed integer;
BEGIN
    SELECT admin_id, required_approvals INTO requester, approvals_needed
      FROM admin_confirmations WHERE id = NEW.confirmation_id;
    IF approvals_needed > 1 AND requester = NEW.approver_admin_id THEN
        RAISE EXCEPTION 'requester cannot provide an independent approval' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$""",
    r"""CREATE TRIGGER trg_admin_approvals_separation
BEFORE INSERT OR UPDATE ON admin_approvals
FOR EACH ROW EXECUTE FUNCTION enforce_approval_separation()""",
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    'DROP TABLE IF EXISTS file_reports CASCADE',
    'DROP TABLE IF EXISTS public_channel_posts CASCADE',
    'DROP TABLE IF EXISTS download_sessions CASCADE',
    'DROP TABLE IF EXISTS user_strikes CASCADE',
    'DROP TABLE IF EXISTS user_appeals CASCADE',
    'DROP TABLE IF EXISTS stream_tokens CASCADE',
    'DROP TABLE IF EXISTS public_share_requests CASCADE',
    'DROP TABLE IF EXISTS media_segments CASCADE',
    'DROP TABLE IF EXISTS download_links CASCADE',
    'DROP TABLE IF EXISTS abuse_actions CASCADE',
    'DROP TABLE IF EXISTS user_restrictions CASCADE',
    'DROP TABLE IF EXISTS usage_records CASCADE',
    'DROP TABLE IF EXISTS support_messages CASCADE',
    'DROP TABLE IF EXISTS stream_sessions CASCADE',
    'DROP TABLE IF EXISTS security_events CASCADE',
    'DROP TABLE IF EXISTS restore_history CASCADE',
    'DROP TABLE IF EXISTS media_variants CASCADE',
    'DROP TABLE IF EXISTS job_events CASCADE',
    'DROP TABLE IF EXISTS file_scan_results CASCADE',
    'DROP TABLE IF EXISTS file_references CASCADE',
    'DROP TABLE IF EXISTS broadcast_results CASCADE',
    'DROP TABLE IF EXISTS bandwidth_usage CASCADE',
    'DROP TABLE IF EXISTS admin_approvals CASCADE',
    'DROP TABLE IF EXISTS user_subscriptions CASCADE',
    'DROP TABLE IF EXISTS user_quota_overrides CASCADE',
    'DROP TABLE IF EXISTS translation_overrides CASCADE',
    'DROP TABLE IF EXISTS support_tickets CASCADE',
    'DROP TABLE IF EXISTS settings_profiles CASCADE',
    'DROP TABLE IF EXISTS settings_history CASCADE',
    'DROP TABLE IF EXISTS quota_reservations CASCADE',
    'DROP TABLE IF EXISTS job_attempts CASCADE',
    'DROP TABLE IF EXISTS files CASCADE',
    'DROP TABLE IF EXISTS file_hash_blocklist CASCADE',
    'DROP TABLE IF EXISTS domain_blocklist CASCADE',
    'DROP TABLE IF EXISTS broadcasts CASCADE',
    'DROP TABLE IF EXISTS bans CASCADE',
    'DROP TABLE IF EXISTS backups CASCADE',
    'DROP TABLE IF EXISTS backup_destinations CASCADE',
    'DROP TABLE IF EXISTS admin_sessions CASCADE',
    'DROP TABLE IF EXISTS admin_scopes CASCADE',
    'DROP TABLE IF EXISTS admin_permission_overrides CASCADE',
    'DROP TABLE IF EXISTS admin_confirmations CASCADE',
    'DROP TABLE IF EXISTS admin_audit_logs CASCADE',
    'DROP TABLE IF EXISTS user_consents CASCADE',
    'DROP TABLE IF EXISTS quota_buckets CASCADE',
    'DROP TABLE IF EXISTS jobs CASCADE',
    'DROP TABLE IF EXISTS admins CASCADE',
    'DROP TABLE IF EXISTS worker_leases CASCADE',
    'DROP TABLE IF EXISTS users CASCADE',
    'DROP TABLE IF EXISTS role_permissions CASCADE',
    'DROP TABLE IF EXISTS webhook_updates CASCADE',
    'DROP TABLE IF EXISTS terms_versions CASCADE',
    'DROP TABLE IF EXISTS telegram_api_capabilities CASCADE',
    'DROP TABLE IF EXISTS subscription_plans CASCADE',
    'DROP TABLE IF EXISTS storage_statistics CASCADE',
    'DROP TABLE IF EXISTS settings CASCADE',
    'DROP TABLE IF EXISTS public_categories CASCADE',
    'DROP TABLE IF EXISTS privacy_versions CASCADE',
    'DROP TABLE IF EXISTS permissions CASCADE',
    'DROP TABLE IF EXISTS outbox_events CASCADE',
    'DROP TABLE IF EXISTS forced_join_channels CASCADE',
    'DROP TABLE IF EXISTS application_instances CASCADE',
    'DROP TABLE IF EXISTS advertisements CASCADE',
    'DROP TABLE IF EXISTS admin_roles CASCADE',
    'DROP FUNCTION IF EXISTS enforce_approval_separation() CASCADE',
    'DROP FUNCTION IF EXISTS protect_system_admin_role() CASCADE',
    'DROP FUNCTION IF EXISTS protect_last_super_admin() CASCADE',
    'DROP FUNCTION IF EXISTS prevent_immutable_mutation() CASCADE',
    'DROP FUNCTION IF EXISTS validate_job_state_transition() CASCADE',
    'DROP FUNCTION IF EXISTS set_row_updated_at() CASCADE',
)

def upgrade() -> None:
    """Create all tables, indexes, constraints, and integrity triggers."""

    for statement in UPGRADE_STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    """Remove the initial schema in dependency-safe order."""

    for statement in DOWNGRADE_STATEMENTS:
        op.execute(sa.text(statement))
