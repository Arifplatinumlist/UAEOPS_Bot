-- Run this once in your Supabase SQL editor or via the CLI

create extension if not exists vector;

create table if not exists documents (
  id         uuid default gen_random_uuid() primary key,
  source     text not null,
  title      text,
  content    text not null,
  metadata   jsonb default '{}'::jsonb,
  embedding  vector(384),
  created_at timestamptz default now()
);

create index if not exists documents_embedding_idx
  on documents using ivfflat (embedding vector_cosine_ops)
  with (lists = 50);

-- Semantic similarity search function
create or replace function search_documents(
  query_embedding vector(384),
  match_count     int     default 5,
  match_threshold float   default 0.3
)
returns table (
  id         uuid,
  source     text,
  title      text,
  content    text,
  metadata   jsonb,
  similarity float
)
language sql stable as $$
  select
    id, source, title, content, metadata,
    1 - (embedding <=> query_embedding) as similarity
  from documents
  where 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;
