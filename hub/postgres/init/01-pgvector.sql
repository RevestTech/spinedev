-- Hub postgres first-boot init — pgvector before Flyway V2+ migrations.
CREATE EXTENSION IF NOT EXISTS vector;
