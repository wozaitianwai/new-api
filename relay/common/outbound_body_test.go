package common

import (
	"io"
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestOutboundJSONBodyCanReplayIdenticalBytes(t *testing.T) {
	payload := []byte(`{"model":"test","value":0}`)
	body, size, closer, err := NewOutboundJSONBody(payload)
	require.NoError(t, err)
	defer closer.Close()

	req, err := http.NewRequest(http.MethodPost, "http://example.test/v1", body)
	require.NoError(t, err)
	req.ContentLength = size
	AttachRequestBodyReplay(req, body)
	require.NotNil(t, req.GetBody)

	first, err := io.ReadAll(req.Body)
	require.NoError(t, err)
	replay, err := req.GetBody()
	require.NoError(t, err)
	defer replay.Close()
	second, err := io.ReadAll(replay)
	require.NoError(t, err)
	assert.Equal(t, payload, first)
	assert.Equal(t, first, second)
	assert.Equal(t, int64(len(payload)), req.ContentLength)
}
