from sqlalchemy import select
from unifi_api.db.models import AuditLog

from tests.graphql.fixtures._helpers import graphql_query
from tests.sitemanager_data import bootstrap


async def query_case(tmp_path, monkeypatch, case):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        body = await graphql_query(app, key, "{ sitemanager { " + case[6] + " } }")
        assert body.get("errors") is None, body
        async with app.state.sessionmaker() as session:
            assert (await session.scalars(select(AuditLog))).all() == []
        getattr(getattr(factory.bundle, case[4]), case[5]).assert_awaited_once()
        return body["data"]["sitemanager"][case[7]]
    finally:
        await app.state.engine.dispose()
