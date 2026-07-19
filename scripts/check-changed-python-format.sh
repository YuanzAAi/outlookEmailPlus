#!/usr/bin/env bash
set -euo pipefail

base_sha="${FORMAT_BASE_SHA:-}"
if [[ -z "$base_sha" || "$base_sha" =~ ^0+$ ]] || ! git rev-parse --verify "${base_sha}^{commit}" >/dev/null 2>&1; then
    if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
        base_sha="HEAD^"
    else
        base_sha="$(git hash-object -t tree /dev/null)"
    fi
fi

mapfile -d '' changed_files < <(
    git diff --name-only --diff-filter=ACMR -z "$base_sha" HEAD -- '*.py'
)

if (( ${#changed_files[@]} == 0 )); then
    echo "No changed Python files to format-check."
    exit 0
fi

printf 'Format-checking %d changed Python files:\n' "${#changed_files[@]}"
printf '  %s\n' "${changed_files[@]}"
black --check "${changed_files[@]}"
isort --check-only --profile black "${changed_files[@]}"
