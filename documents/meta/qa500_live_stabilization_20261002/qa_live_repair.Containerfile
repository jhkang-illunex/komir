FROM komir-rag-chat:qa-live-repair32
WORKDIR /app
COPY common ./common
COPY rag_core/ragkit ./rag_core/ragkit
COPY rag_core/retrieval ./rag_core/retrieval
COPY rag_chat/app ./app
