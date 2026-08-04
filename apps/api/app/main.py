from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import SessionLocal, init_database
from .routers.auth import router as auth_router
from .routers.announcements import router as announcements_router
from .routers.access_control import router as access_control_router
from .routers.health import router as health_router
from .routers.image_intelligence import router as image_intelligence_router
from .routers.inventory import router as inventory_router
from .routers.knowledge_search import router as knowledge_search_router
from .routers.legacy_operations import router as legacy_operations_router
from .routers.product_intelligence import router as product_intelligence_router
from .routers.product_center import router as product_center_router
from .routers.platform_admin import router as platform_admin_router
from .routers.system import router as system_router
from .routers.storefront_analytics import router as storefront_analytics_router
from .routers.support import router as support_router
from .routers.tags import router as tags_router
from .routers.trade_flow import router as trade_flow_router
from .routers.public_catalog import router as public_catalog_router
from .routers.quote_templates import router as quote_templates_router
from .routers.customer_accounts import router as customer_accounts_router
from .routers.catalog_translations import router as catalog_translations_router
from .routers.workspace import router as workspace_router
from .runtime_config import cors_origins, validate_startup_configuration
from .saas_seed import demo_seed_enabled, seed_saas_foundation
from .product_center_seed import seed_product_center_demo
from .services.repository import seed_suppliers
from .use_cases.legacy_operations import resume_deferred_imports
def _initialize_runtime() -> None:
    validate_startup_configuration()
    init_database()
    if demo_seed_enabled():
        with SessionLocal() as session:
            seed_saas_foundation(session)
            seed_suppliers(session)
            seed_product_center_demo(session)
    resume_deferred_imports()


def create_app() -> FastAPI:
    application = FastAPI(
        title="智贸云 API",
        version="0.3.0",
        description="AI 原生外贸平台 API：可信租户上下文、供应商导入、产品审核与知识检索。",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        health_router,
        auth_router,
        announcements_router,
        access_control_router,
        legacy_operations_router,
        product_intelligence_router,
        product_center_router,
        inventory_router,
        platform_admin_router,
        image_intelligence_router,
        trade_flow_router,
        public_catalog_router,
        quote_templates_router,
        customer_accounts_router,
        catalog_translations_router,
        workspace_router,
        knowledge_search_router,
        system_router,
        storefront_analytics_router,
        support_router,
        tags_router,
    ):
        application.include_router(router)
    return application
_initialize_runtime()
app = create_app()
