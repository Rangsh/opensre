"""Shrink-only allowlist for pre-existing actionable-description debt (#5500).

Compared exactly in both directions: a new violation fails; a fixed description
must drop its entry here. Per-source counts at quarantine time:

  github             45
  hermes             19
  redis              7
  bitbucket          6
  knowledge          6
  gitlab             5
  helm               5
  mongodb_atlas      5
  yandex_cloud       5
  airflow            4
  interactive_shell  4
  openobserve        4
  tracer_web         4
  cloudwatch         3
  slack              3
  snowflake          3
  azure              2
  betterstack        2
  clickhouse         2
  ec2                2
  grafana            2
  openclaw           2
  opensearch         2
  rds                2
  sentry             2
  azure_sql          1
  coralogix          1
  dagster            1
  honeycomb          1
  incident_io        1
  kafka              1
  kubernetes         1
  tempo              1
"""

from __future__ import annotations

ACTIONABLE_PROPERTY_DESCRIPTION_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("alert_sample", "template", "enum_values"),
        ("describe_rds_events", "db_instance_identifier", "identifier_kind"),
        ("describe_rds_events", "duration_minutes", "time_unit_and_format"),
        ("ec2_instances_by_tag", "instance_ids", "identifier_kind"),
        ("ec2_instances_by_tag", "vpc_id", "identifier_kind"),
        ("execute_github_issue_mutation", "owner", "identifier_kind"),
        ("execute_github_issue_mutation", "repo", "identifier_kind"),
        ("fix_github_security_alert", "alert_type", "enum_values"),
        ("generate_work_status_report", "owner", "identifier_kind"),
        ("generate_work_status_report", "repo", "identifier_kind"),
        ("get_airflow_dag_runs", "dag_id", "identifier_kind"),
        ("get_airflow_metrics", "trace_id", "identifier_kind"),
        ("get_airflow_task_instances", "dag_id", "identifier_kind"),
        ("get_airflow_task_instances", "dag_run_id", "identifier_kind"),
        ("get_azure_sql_resource_stats", "minutes", "time_unit_and_format"),
        ("get_batch_statistics", "trace_id", "identifier_kind"),
        ("get_bitbucket_file_contents", "integration_id", "identifier_kind"),
        ("get_bitbucket_file_contents", "username", "identifier_kind"),
        ("get_clickhouse_query_activity", "username", "identifier_kind"),
        ("get_clickhouse_system_health", "username", "identifier_kind"),
        ("get_cloudwatch_batch_metrics", "metric_type", "enum_values"),
        ("get_dagster_run_logs", "run_id", "identifier_kind"),
        ("get_error_logs", "trace_id", "identifier_kind"),
        ("get_failed_tools", "trace_id", "identifier_kind"),
        ("get_git_deploy_timeline", "owner", "identifier_kind"),
        ("get_git_deploy_timeline", "repo", "identifier_kind"),
        ("get_github_actions_step_log", "job_id", "identifier_kind"),
        ("get_github_actions_step_log", "owner", "identifier_kind"),
        ("get_github_actions_step_log", "repo", "identifier_kind"),
        ("get_github_actions_step_log", "run_id", "identifier_kind"),
        ("get_github_file_contents", "owner", "identifier_kind"),
        ("get_github_file_contents", "repo", "identifier_kind"),
        ("get_github_repository", "owner", "identifier_kind"),
        ("get_github_repository", "repo", "identifier_kind"),
        ("get_github_repository_tree", "owner", "identifier_kind"),
        ("get_github_repository_tree", "repo", "identifier_kind"),
        ("get_gitlab_file", "project_id", "identifier_kind"),
        ("get_hermes_adapter_catalog", "session_id", "identifier_kind"),
        ("get_hermes_approval_events", "session_id", "identifier_kind"),
        ("get_hermes_audit_trail", "session_id", "identifier_kind"),
        ("get_hermes_config", "session_id", "identifier_kind"),
        ("get_hermes_credential_state", "session_id", "identifier_kind"),
        ("get_hermes_cron_state", "session_id", "identifier_kind"),
        ("get_hermes_filesystem_state", "session_id", "identifier_kind"),
        ("get_hermes_kv_cache_state", "session_id", "identifier_kind"),
        ("get_hermes_logs", "levels", "enum_values"),
        ("get_hermes_memory_state", "session_id", "identifier_kind"),
        ("get_hermes_message_history", "session_id", "identifier_kind"),
        ("get_hermes_orchestration_state", "session_id", "identifier_kind"),
        ("get_hermes_provider_traffic", "session_id", "identifier_kind"),
        ("get_hermes_rbac_state", "session_id", "identifier_kind"),
        ("get_hermes_routing_decisions", "session_id", "identifier_kind"),
        ("get_hermes_runtime_state", "session_id", "identifier_kind"),
        ("get_hermes_session_log", "session_id", "identifier_kind"),
        ("get_hermes_session_topology", "session_id", "identifier_kind"),
        ("get_hermes_workflow_run", "session_id", "identifier_kind"),
        ("get_host_metrics", "trace_id", "identifier_kind"),
        ("get_kafka_consumer_group_lag", "group_id", "identifier_kind"),
        ("get_lambda_invocation_logs", "request_id", "identifier_kind"),
        ("get_mongodb_atlas_alerts", "project_id", "identifier_kind"),
        ("get_mongodb_atlas_cluster_events", "project_id", "identifier_kind"),
        ("get_mongodb_atlas_cluster_metrics", "project_id", "identifier_kind"),
        ("get_mongodb_atlas_clusters", "project_id", "identifier_kind"),
        ("get_mongodb_atlas_performance_advisor", "project_id", "identifier_kind"),
        ("get_openclaw_conversation", "conversation_id", "identifier_kind"),
        ("get_recent_airflow_failures", "dag_id", "identifier_kind"),
        ("get_redis_client_list", "username", "identifier_kind"),
        ("get_redis_latency_doctor", "username", "identifier_kind"),
        ("get_redis_list_depth", "username", "identifier_kind"),
        ("get_redis_replication", "username", "identifier_kind"),
        ("get_redis_server_info", "username", "identifier_kind"),
        ("get_redis_slowlog", "username", "identifier_kind"),
        ("get_sentry_issue_details", "issue_id", "identifier_kind"),
        ("get_yc_lb_health", "type", "enum_values"),
        ("helm_get_release_manifest", "integration_id", "identifier_kind"),
        ("helm_get_release_values", "integration_id", "identifier_kind"),
        ("helm_list_releases", "integration_id", "identifier_kind"),
        ("helm_release_history", "integration_id", "identifier_kind"),
        ("helm_release_status", "integration_id", "identifier_kind"),
        ("incident_io_incidents", "action", "enum_values"),
        ("kubernetes_get_resource", "resource_type", "enum_values"),
        ("list_bitbucket_commits", "integration_id", "identifier_kind"),
        ("list_bitbucket_commits", "username", "identifier_kind"),
        ("list_github_actions_active_runs", "owner", "identifier_kind"),
        ("list_github_actions_active_runs", "repo", "identifier_kind"),
        ("list_github_actions_run_jobs", "owner", "identifier_kind"),
        ("list_github_actions_run_jobs", "repo", "identifier_kind"),
        ("list_github_actions_run_jobs", "run_id", "identifier_kind"),
        ("list_github_actions_workflow_runs", "owner", "identifier_kind"),
        ("list_github_actions_workflow_runs", "repo", "identifier_kind"),
        ("list_github_commits", "owner", "identifier_kind"),
        ("list_github_commits", "repo", "identifier_kind"),
        ("list_github_security_alerts", "alert_type", "enum_values"),
        ("list_github_security_alerts", "owner", "identifier_kind"),
        ("list_github_security_alerts", "repo", "identifier_kind"),
        ("list_github_work_items", "owner", "identifier_kind"),
        ("list_github_work_items", "repo", "identifier_kind"),
        ("list_github_work_items", "state", "enum_values"),
        ("list_gitlab_commits", "project_id", "identifier_kind"),
        ("list_gitlab_commits", "since", "time_unit_and_format"),
        ("list_gitlab_mrs", "project_id", "identifier_kind"),
        ("list_gitlab_pipelines", "project_id", "identifier_kind"),
        ("list_sentry_issue_events", "issue_id", "identifier_kind"),
        ("memory_remember", "type", "enum_values"),
        ("propose_github_issue_mutation_from_slack", "operation", "enum_values"),
        ("propose_github_issue_mutation_from_slack", "owner", "identifier_kind"),
        ("propose_github_issue_mutation_from_slack", "repo", "identifier_kind"),
        ("query_azure_monitor_logs", "integration_id", "identifier_kind"),
        ("query_azure_monitor_logs", "timeout_seconds", "time_unit_and_format"),
        ("query_betterstack_logs", "since", "time_unit_and_format"),
        ("query_betterstack_logs", "until", "time_unit_and_format"),
        ("query_coralogix_logs", "trace_id", "identifier_kind"),
        ("query_grafana_logs", "execution_run_id", "identifier_kind"),
        ("query_grafana_traces", "execution_run_id", "identifier_kind"),
        ("query_honeycomb_traces", "trace_id", "identifier_kind"),
        ("query_openobserve_logs", "integration_id", "identifier_kind"),
        ("query_openobserve_logs", "org", "identifier_kind"),
        ("query_openobserve_logs", "timeout_seconds", "time_unit_and_format"),
        ("query_openobserve_logs", "username", "identifier_kind"),
        ("query_opensearch_analytics", "integration_id", "identifier_kind"),
        ("query_opensearch_analytics", "username", "identifier_kind"),
        ("query_snowflake_history", "integration_id", "identifier_kind"),
        ("query_snowflake_history", "timeout_seconds", "time_unit_and_format"),
        ("query_snowflake_history", "user", "identifier_kind"),
        ("query_tempo", "action", "enum_values"),
        ("query_yc_metrics", "aggregation", "enum_values"),
        ("query_yc_metrics", "window_minutes", "time_unit_and_format"),
        ("read_yc_logs", "levels", "enum_values"),
        ("read_yc_logs", "window_minutes", "time_unit_and_format"),
        ("scan_redis_keys", "username", "identifier_kind"),
        ("search_bitbucket_code", "integration_id", "identifier_kind"),
        ("search_bitbucket_code", "username", "identifier_kind"),
        ("search_github_code", "owner", "identifier_kind"),
        ("search_github_code", "repo", "identifier_kind"),
        ("search_github_issues", "owner", "identifier_kind"),
        ("search_github_issues", "repo", "identifier_kind"),
        ("search_github_issues", "state", "enum_values"),
        ("send_openclaw_message", "conversation_id", "identifier_kind"),
        ("slack_add_reaction", "timestamp", "time_unit_and_format"),
        ("slack_read_messages", "thread_ts", "time_unit_and_format"),
        ("slack_reply_message", "thread_ts", "time_unit_and_format"),
        ("slash_invoke", "command", "enum_values"),
        ("summarize_community_followups", "owner", "identifier_kind"),
        ("summarize_community_followups", "repo", "identifier_kind"),
        ("summarize_github_pr_status", "owner", "identifier_kind"),
        ("summarize_github_pr_status", "repo", "identifier_kind"),
        ("summarize_github_pr_status", "state", "enum_values"),
        ("synthetic_run", "scenario", "enum_values"),
        ("synthetic_run", "suite", "enum_values"),
        ("work_task_add", "priority", "enum_values"),
        ("work_task_update", "channel_id", "identifier_kind"),
        ("work_task_update", "owner", "identifier_kind"),
        ("work_task_update", "priority", "enum_values"),
        ("work_task_update", "status", "enum_values"),
    }
)
