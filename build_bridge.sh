#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AS2_HOME="${AS2_HOME:-$(dirname "$SCRIPT_DIR")}"

echo "AS2_HOME: $AS2_HOME"

cp "$SCRIPT_DIR/AS2Bridge.java" "$AS2_HOME/AS2Bridge.java"

CP="$AS2_HOME/as2.jar:$AS2_HOME"
for jar in "$AS2_HOME"/jlib/*.jar \
           "$AS2_HOME"/jlib/mina/*.jar \
           "$AS2_HOME"/jlib/jackson/*.jar \
           "$AS2_HOME"/jlib/oshi/*.jar \
           "$AS2_HOME"/jlib/httpclient/*.jar \
           "$AS2_HOME"/jlib/db/*.jar; do
    [ -f "$jar" ] && CP="$CP:$jar"
done

javac -cp "$CP" -d "$AS2_HOME" "$AS2_HOME/AS2Bridge.java"
echo "AS2Bridge compiled successfully -> $AS2_HOME/AS2Bridge.class"
