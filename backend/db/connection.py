from __future__ import annotations

import asyncpg
from asyncpg import Pool
from loguru import logger

_pool: Pool | None = None


async def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def init_db(database_url: str) -> None:
    global _pool
    logger.info("Initializing database connection pool...")
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    await create_tables()
    logger.info("Database pool ready.")


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")


async def create_tables() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pr_url TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                pr_title TEXT,
                diff_content TEXT,
                status TEXT DEFAULT 'queued',
                risk_level TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_traces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_id UUID REFERENCES jobs(id),
                agent_name TEXT NOT NULL,
                model_used TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                latency_ms INTEGER,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS generated_tests (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_id UUID REFERENCES jobs(id),
                test_type TEXT NOT NULL,
                file_content TEXT NOT NULL,
                file_path TEXT NOT NULL,
                pass_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                coverage_delta FLOAT DEFAULT 0.0,
                repair_attempts INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

    logger.info("Database tables created (if not existed).")
