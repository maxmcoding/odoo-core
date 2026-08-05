#!/usr/bin/env bash

CUSTOM_GOAL="try start match with MATCH (n:PythonModel) limit 1   then work with related nodes | "
# Store content in a variable, prefixed with custom indications
GOAL="$CUSTOM_GOAL"$'\n\n'"$(< fillcontextbynode.md)"
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
        echo "Task completed successfully! ... Wating to restart over"
        sleep $DELAY_SECONDS
        # exit 0
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