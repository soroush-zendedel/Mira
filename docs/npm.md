# npm registries

Mira supports `npm list`, `npm check`, `npm current`, `npm set`, and `npm reset`.
`set` changes the default `registry` value in an npm `.npmrc`; authentication
tokens, comments, and scoped registry entries are preserved.

```sh
mira npm list
mira npm check --refresh
mira npm set --scope user --dry-run
mira npm set --scope user
mira npm reset --scope user
mira npm reset --scope project
```

The `--scope` values are `user` (default), `project` (the current directory's
`.npmrc`), and `system`. `mira reset --provider npm` resets user and current
project configuration. npm registry changes also affect publish commands;
publish directly to the intended writable registry with npm's `--registry`
option when needed.

The Iran list currently includes Runflare, Novin Cloud, and Kargadan based on
their published npm registry instructions. The other configured countries use
the official public npm registry as a global option; they are not represented
as hosting local mirrors. The official npm documentation identifies
`https://registry.npmjs.org/` as npm's default registry. Availability can vary
by network and mirror operators can change service terms or limits.

Sources:

- [Runflare npm mirror setup](https://runflare.com/mirrors/npm-mirror/)
- [Novin Cloud npm mirror instructions](https://novin.cloud/en/blog/npm-mirror-iran)
- [Kargadan mirror instructions](https://www.t.me/s/kargadan_ir)
- [npm registry documentation](https://docs.npmjs.com/misc/registry/)
