#!/usr/bin/env bash

# GOAL="Create entities and relations on neo4j memory for .py files in this workspace"
# Store content in a variable
GOAL=$(< fillcontextbynode.md)
MAX_RETRIES=10222
RETRY_COUNT=0
DELAY_SECONDS=5

echo "Starting Cline loop for goal "

# echo "GOAL:: '$GOAL'"]

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo "--- Attempt $((RETRY_COUNT+1)) of $MAX_RETRIES ---"
    
    # Run Cline CLI in autonomous mode with LM Studio base URL
    cline --provider lmstudio \
		--model qwen/qwen3.5-9b  \
		"$GOAL"

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "Task completed successfully!"
        exit 0
    else
        echo "Cline crashed or LM Studio threw an error (Exit code: $EXIT_CODE)."
        RETRY_COUNT=$((RETRY_COUNT+1))
        
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            echo "Waiting $DELAY_SECONDS seconds before restarting..."
            sleep $DELAY_SECONDS
        fi
    fi
done

echo "Reached maximum retry limit."
exit 1