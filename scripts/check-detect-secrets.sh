#!/usr/bin/env bash
set -euo pipefail

mode="${1:-"--all-files"}"
ignore_globs=("scripts/check-detect-secrets.sh")
if [[ -f .detect-secrets-ignore ]]; then
  while IFS= read -r ignore_glob; do
    if [[ -z "$ignore_glob" ]]; then
      continue
    fi
    if [[ "${ignore_glob:0:1}" == "#" ]]; then
      continue
    fi
    ignore_globs+=("$ignore_glob")
  done < .detect-secrets-ignore
fi

should_skip_file() {
  local candidate="$1"
  local ignore_glob
  for ignore_glob in "${ignore_globs[@]}"; do
    case "$candidate" in
      $ignore_glob)
        return 0
        ;;
    esac
  done
  return 1
}

append_tracked_files() {
  while IFS= read -r -d '' file; do
    files+=("$file")
  done < <(git ls-files -z)
}

append_staged_files() {
  while IFS= read -r -d '' file; do
    files+=("$file")
  done < <(git diff --cached --name-only --diff-filter=ACMR -z)
}

append_untracked_files() {
  while IFS= read -r -d '' file; do
    files+=("$file")
  done < <(git ls-files --others --exclude-standard -z)
}

files=()
case "$mode" in
  --staged)
    append_staged_files
    ;;
  --all-files)
    append_tracked_files
    ;;
  --all-files-with-untracked | --all-local | --local)
    append_tracked_files
    append_untracked_files
    ;;
  *)
    echo "Usage: $0 [--all-files|--staged|--all-files-with-untracked|--all-local|--local]" >&2
    exit 2
    ;;
esac

if [[ "${#files[@]}" -eq 0 ]]; then
  echo "No files to scan."
  exit 0
fi

content_patterns=(
  'ghp_'
  'github_pat_'
  'sk-live-'
  'sk-proj-'
  'AKIA[0-9A-Z]{16}'
  'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY'
  'ANTHROPIC_API_KEY='
  'OPENAI_API_KEY='
  'SUDO_PASS='
  'BW_SESSION='
)

mailplus_content_patterns=(
  'https?://[^[:space:])>"]*(oauth|authorize|token)[^[:space:])>"]*(token|code|key|secret|signature|sig|jwt|session|auth)='
  'https?://[^[:space:])>"]*(reset|recovery|recover-password|password-reset|magic|login)[^[:space:])>"]*(token|code|key|secret|signature|sig|jwt|session|auth)='
  'https?://[^[:space:])>"]*(pay|payment|checkout|invoice|billing)[^[:space:])>"]*(token|code|key|secret|signature|sig|jwt|session|auth)='
)

mailplus_path_patterns=(
  '\.eml$'
  '\.mbox$'
  '(^|/)(mailplus|selected-text|semantic|metadata)[^/]*\.(db|sqlite|sqlite3)$'
  '(^|/)(mailplus|selected-text|semantic|metadata)[^/]*\.(cache|log)$'
)

allowed_synthetic_pattern='(example\.(com|org|net|test)|\[REDACTED_[A-Z_]+\])'

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT

for file in "${files[@]}"; do
  if [[ ! -f "$file" ]] || should_skip_file "$file"; then
    continue
  fi
  printf '%s\n' "$file" >>"$tmp_file"
done

failed=0
while IFS= read -r file; do
  for pattern in "${mailplus_path_patterns[@]}"; do
    if [[ "$file" =~ $pattern ]]; then
      echo "Potential MailPlus export/cache artifact '$pattern' found at $file" >&2
      failed=1
    fi
  done

  for pattern in "${content_patterns[@]}"; do
    if grep -E -n "$pattern" "$file" >/dev/null 2>&1; then
      echo "Potential secret pattern '$pattern' found in $file" >&2
      failed=1
    fi
  done

  for pattern in "${mailplus_content_patterns[@]}"; do
    if grep -E -n "$pattern" "$file" | grep -Ev "$allowed_synthetic_pattern" >/dev/null 2>&1; then
      echo "Potential MailPlus link leak pattern '$pattern' found in $file" >&2
      failed=1
    fi
  done
done <"$tmp_file"

exit "$failed"
