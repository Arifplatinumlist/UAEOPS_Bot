-- Update documents table to use Voyage AI voyage-3-lite dimensions (512)
create extension if not exists vector;

drop function if exists search_documents(vector, int, float);
drop index if exists documents_embedding_idx;
drop table if exists documents;

create table documents (
  id         uuid        default gen_random_uuid() primary key,
  source     text        not null,
  title      text,
  content    text        not null,
  metadata   jsonb       default '{}'::jsonb,
  embedding  vector(512),
  created_at timestamptz default now()
);

create index documents_embedding_idx
  on documents using ivfflat (embedding vector_cosine_ops)
  with (lists = 50);

create or replace function search_documents(
  query_embedding vector(512),
  match_count     int   default 5,
  match_threshold float default 0.4
)
returns table (id uuid, source text, title text, content text, metadata jsonb, similarity float)
language sql stable as $$
  select id, source, title, content, metadata,
    1 - (embedding <=> query_embedding) as similarity
  from documents
  where 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;
