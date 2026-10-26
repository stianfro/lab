# Run with fish --no-config --interactive to avoid personal configuration.
source $argv[1]; or exit 1

function _pure_user_at_host
    echo tester@devbox
end

set --global pure_symbol_ssh_prefix 'ssh: '
set --erase SSH_CONNECTION
set --erase REX_SERVER

test (_pure_prompt_ssh) = tester@devbox; or exit 1
not set --query SSH_CONNECTION; or exit 1

set --global REX_SERVER unix:///run/user/1000/rex/server.sock
test (_pure_prompt_ssh) = tester@devbox; or exit 1
not set --query SSH_CONNECTION; or exit 1

set --global SSH_CONNECTION '192.0.2.1 1234 192.0.2.2 22'
test (_pure_prompt_ssh) = 'ssh: tester@devbox'; or exit 1
test "$SSH_CONNECTION" = '192.0.2.1 1234 192.0.2.2 22'; or exit 1

set --global pure_symbol_ssh_prefix ''
test (_pure_prompt_ssh) = tester@devbox; or exit 1
printf 'Devbox prompt tests passed\n'
