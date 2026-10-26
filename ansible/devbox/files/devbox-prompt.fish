# Managed by Ansible, outside the personal fish configuration sync.
status is-interactive; or return

# Pure normally hides this component unless SSH_CONNECTION is present.
# Rex shells are local to the server, but still need a visible user@host.
function _pure_prompt_ssh --description 'Identify the devbox in every Pure prompt'
    set --local prefix ''
    if test -n "$SSH_CONNECTION"
        set prefix "$pure_symbol_ssh_prefix"
    end
    printf '%s%s\n' "$prefix" (_pure_user_at_host)
end
