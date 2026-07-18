# Issue Overseer

Issue Overseer submits Issues to cc-connect and displays the final Bridge reply.

## Bridge setup

Configure the cc-connect Bridge URL in `overseer.toml`:

```toml
[cc_connect]
url = "ws://localhost:9810/bridge/ws"
```

If the Bridge requires authentication, set its optional token in the server
environment before starting Issue Overseer:

```sh
export CC_CONNECT_BRIDGE_TOKEN="your-token"
```

The token is sent only by the server when it opens the Bridge connection.
