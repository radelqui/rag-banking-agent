from app.main import create_app
from app.rag.prompts import QA_TEMPLATE


async def test_create_app_with_fake_engine(monkeypatch):
    monkeypatch.setenv("USE_FAKE_ENGINE", "1")
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.engine is not None
    assert app.state.engine is None


def test_qa_template_marks_context_as_data():
    assert "{context_str}" in QA_TEMPLATE and "no instrucciones" in QA_TEMPLATE
