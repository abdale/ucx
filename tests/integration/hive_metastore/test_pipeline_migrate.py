from venv import create

from databricks.labs.ucx.assessment.pipelines import PipelinesCrawler
from databricks.labs.ucx.hive_metastore.pipelines_migrate import PipelinesMigrator, PipelineRule, PipelineMapping

_TEST_STORAGE_ACCOUNT = "storage_acct_1"
_TEST_TENANT_ID = "directory_12345"

_PIPELINE_CONF = {
    f"spark.hadoop.fs.azure.account.oauth2.client.id.{_TEST_STORAGE_ACCOUNT}.dfs.core.windows.net": ""
                                                                                                    "pipeline_dummy_application_id",
    f"spark.hadoop.fs.azure.account.oauth2.client.endpoint.{_TEST_STORAGE_ACCOUNT}.dfs.core.windows.net": ""
                                                                                                          "https://login"
                                                                                                          f".microsoftonline.com/{_TEST_TENANT_ID}/oauth2/token",
}

_PIPELINE_CONF_WITH_SECRET = {
    "fs.azure.account.oauth2.client.id.abcde.dfs.core.windows.net": "{{secrets/reallyasecret123/sp_app_client_id}}",
    "fs.azure.account.oauth2.client.endpoint.abcde.dfs.core.windows.net": "https://login.microsoftonline.com"
                                                                          "/dummy_application/token",
}


def test_pipeline_migrate(ws, make_pipeline, inventory_schema,
                          sql_backend, runtime_ctx):

        created_pipeline = make_pipeline(configuration=_PIPELINE_CONF)
        pipeline_crawler = PipelinesCrawler(ws=ws, sbe=sql_backend, schema=inventory_schema)
        pipelines = pipeline_crawler.snapshot()

        results = []
        for pipeline in pipelines:
            if pipeline.success != 0:
                continue
            if pipeline.pipeline_id == created_pipeline.pipeline_id:
                results.append(pipeline)

        assert len(results) >= 1
        assert results[0].pipeline_id == created_pipeline.pipeline_id

        pipeline_rules = [
            PipelineRule.from_src_dst(created_pipeline.pipeline_id, "test_catalog")
        ]
        runtime_ctx.with_pipeline_mapping_rules(pipeline_rules)
        pipeline_mapping = PipelineMapping(
            runtime_ctx.installation,
            ws,
            sql_backend
        )

        pipelines_migrator = PipelinesMigrator(ws, pipeline_crawler, pipeline_mapping)
        pipelines_migrator.migrate_pipelines()

