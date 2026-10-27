#!/usr/bin/env bash
# Publish complete release assets, preserving recoverable drafts on failure.
set -euo pipefail

: "${GH_REPO:?GH_REPO must identify the GitHub repository}"
: "${GITHUB_SHA:?GITHUB_SHA must identify the commit being released}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

version=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
tag="v${version}"
ref="refs/tags/${tag}"
assets=(
  "dist/ae5ctl-${version}-py3-none-any.whl"
  "dist/ae5ctl-${version}.tar.gz"
  "dist/ae5ctl_${version}_all.deb"
)
for asset in "${assets[@]}"; do
  if [[ ! -s "$asset" ]]; then
    echo "Missing release artifact: ${asset}" >&2
    exit 1
  fi
done

# ls-remote preserves the existing proxy and authentication. Prefer an annotated
# tag's peeled commit over the tag object's SHA; lightweight tags work too.
remote_refs=$(git ls-remote --tags origin "$ref" "${ref}^{}")
tag_commit=$(awk -v tag="$ref" '
  $2 == tag { commit=$1 }
  $2 == tag "^{}" { peeled=$1 }
  END { print peeled ? peeled : commit }
' <<< "$remote_refs")
if [[ -n "$tag_commit" && "$tag_commit" != "$GITHUB_SHA" ]]; then
  echo "${tag} already belongs to ${tag_commit}; increment project.version for ${GITHUB_SHA}." >&2
  exit 1
fi

# Listing succeeds with empty output when no release exists. Authentication or
# network failures remain fatal instead of being mistaken for a missing release.
release_info=$(gh api "repos/${GH_REPO}/releases?per_page=100" --paginate \
  --jq ".[] | select(.tag_name == \"${tag}\") | [.draft, .target_commitish] | @tsv")
is_draft=true
if [[ -n "$release_info" ]]; then
  IFS=$'\t' read -r is_draft release_target <<< "$release_info"
  if [[ -z "$tag_commit" && "$release_target" != "$GITHUB_SHA" ]]; then
    echo "${tag} already targets ${release_target}; increment project.version for ${GITHUB_SHA}." >&2
    exit 1
  fi
else
  gh release create "$tag" --draft --target "$GITHUB_SHA" --title "$tag" --generate-notes
fi

# A failed upload leaves the draft recoverable. Rerunning this commit replaces
# partial assets, and only publishes after every required upload succeeds.
gh release upload "$tag" "${assets[@]}" --clobber
if [[ "$is_draft" == true ]]; then
  gh release edit "$tag" --draft=false
fi
