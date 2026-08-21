#!/usr/bin/env bash


# IMPORTANT AFTER RUN:
# RUn on Cyher database this commands
# 
# MATCH (n)
# WHERE (n.context <> "" and n.context IS NOT NULL)  
# SET n.observations = [x IN [n.context, n.technicalName] WHERE x IS NOT NULL],
#     n.type = [l IN labels(n) WHERE l <> "Memory"][0],
#     n:Memory
# RETURN count(n)
#  
#  --------- THEN RUN
# 
# MATCH (n)
# WHERE n.name IS NULL
# SET n.name = coalesce(n.technicalName,n.filename, n.path, n.filePath, "unnamed_" + elementId(n))
# RETURN count(n)
#  
# --------------------------




CUSTOM_GOAL="try start match with MATCH (n:PythonModel) limit 1   then work with related nodes | No ask me | "
# Store content in a variable, prefixed with custom indications
GOAL="$CUSTOM_GOAL"$'\n\n'"$(< fillcontextbynode.md)"
MAX_RETRIES=10222
RETRY_COUNT=0
DELAY_SECONDS=5
MAX_RUNTIME="35m"

echo "Starting Cline loop for goal "

# echo "GOAL:: '$GOAL'"]

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo "--- Attempt $((RETRY_COUNT+1)) of $MAX_RETRIES ---"

    # Run Cline CLI in autonomous mode with LM Studio base URL, force-killed after $MAX_RUNTIME
    timeout --signal=TERM --kill-after=30s "$MAX_RUNTIME" \
        cline "$GOAL"

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 124 ]; then
        echo "Cline exceeded $MAX_RUNTIME, killed. Restarting..."
        sleep $DELAY_SECONDS
    elif [ $EXIT_CODE -eq 0 ]; then
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
