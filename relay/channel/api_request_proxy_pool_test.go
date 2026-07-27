package channel

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/QuantumNous/new-api/dto"
	relaycommon "github.com/QuantumNous/new-api/relay/common"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type proxyRecorder struct {
	mutex  sync.Mutex
	bodies [][]byte
	calls  int
	status int
}

func (recorder *proxyRecorder) handler(responseBody string) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		body, _ := io.ReadAll(request.Body)
		recorder.mutex.Lock()
		recorder.calls++
		recorder.bodies = append(recorder.bodies, append([]byte(nil), body...))
		recorder.mutex.Unlock()
		writer.WriteHeader(recorder.status)
		_, _ = writer.Write([]byte(responseBody))
	})
}

func (recorder *proxyRecorder) snapshot() (int, [][]byte) {
	recorder.mutex.Lock()
	defer recorder.mutex.Unlock()
	bodies := make([][]byte, len(recorder.bodies))
	for index := range recorder.bodies {
		bodies[index] = append([]byte(nil), recorder.bodies[index]...)
	}
	return recorder.calls, bodies
}

func relayBool(value bool) *bool { return &value }
func relayInt(value int) *int    { return &value }

func newProxyPoolRelayInfo(channelID int, proxies []string, statusCodes []int) *relaycommon.RelayInfo {
	return &relaycommon.RelayInfo{
		ChannelMeta: &relaycommon.ChannelMeta{
			ChannelId: channelID,
			ChannelSetting: dto.ChannelSettings{
				ProxyPoolEnabled:           true,
				ProxyPool:                  proxies,
				ProxyFailoverNetworkErrors: relayBool(true),
				ProxyFailoverStatusCodes:   statusCodes,
				ProxyFailoverMaxAttempts:   len(proxies),
				ProxyCooldownSeconds:       relayInt(60),
			},
		},
	}
}

func newProxyPoolTestContext(t *testing.T, ctx context.Context) *gin.Context {
	t.Helper()
	gin.SetMode(gin.TestMode)
	contextValue, _ := gin.CreateTestContext(httptest.NewRecorder())
	contextValue.Request = httptest.NewRequest(http.MethodPost, "http://client.test/v1", http.NoBody).WithContext(ctx)
	return contextValue
}

func newReplayableProxyRequest(t *testing.T, ctx context.Context, payload []byte) (*http.Request, io.Closer) {
	t.Helper()
	body, size, closer, err := relaycommon.NewOutboundJSONBody(payload)
	require.NoError(t, err)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://upstream.invalid/v1", body)
	require.NoError(t, err)
	request.ContentLength = size
	relaycommon.AttachRequestBodyReplay(request, body)
	return request, closer
}

func TestDoRequestProxyPoolConfiguredStatusesSwitch(t *testing.T) {
	for _, statusCode := range []int{400, 401, 403, 404, 429, 502, 503, 504} {
		t.Run(http.StatusText(statusCode), func(t *testing.T) {
			firstRecorder := &proxyRecorder{status: statusCode}
			secondRecorder := &proxyRecorder{status: http.StatusOK}
			firstProxy := httptest.NewServer(firstRecorder.handler("first"))
			defer firstProxy.Close()
			secondProxy := httptest.NewServer(secondRecorder.handler("second"))
			defer secondProxy.Close()

			ctx := context.Background()
			ginContext := newProxyPoolTestContext(t, ctx)
			payload := []byte(`{"model":"test"}`)
			request, closer := newReplayableProxyRequest(t, ctx, payload)
			defer closer.Close()
			info := newProxyPoolRelayInfo(10_000+statusCode, []string{firstProxy.URL, secondProxy.URL}, []int{statusCode})

			response, err := DoRequest(ginContext, request, info)
			require.NoError(t, err)
			defer response.Body.Close()
			assert.Equal(t, http.StatusOK, response.StatusCode)

			firstCalls, firstBodies := firstRecorder.snapshot()
			secondCalls, secondBodies := secondRecorder.snapshot()
			assert.Equal(t, 1, firstCalls)
			assert.Equal(t, 1, secondCalls)
			require.Len(t, firstBodies, 1)
			require.Len(t, secondBodies, 1)
			assert.Equal(t, payload, firstBodies[0])
			assert.Equal(t, firstBodies[0], secondBodies[0])
		})
	}
}

func TestDoRequestProxyPoolUnconfiguredStatusDoesNotSwitch(t *testing.T) {
	firstRecorder := &proxyRecorder{status: http.StatusUnauthorized}
	secondRecorder := &proxyRecorder{status: http.StatusOK}
	firstProxy := httptest.NewServer(firstRecorder.handler("first"))
	defer firstProxy.Close()
	secondProxy := httptest.NewServer(secondRecorder.handler("second"))
	defer secondProxy.Close()

	ctx := context.Background()
	ginContext := newProxyPoolTestContext(t, ctx)
	request, closer := newReplayableProxyRequest(t, ctx, []byte(`{"model":"test"}`))
	defer closer.Close()
	info := newProxyPoolRelayInfo(20_001, []string{firstProxy.URL, secondProxy.URL}, []int{429})

	response, err := DoRequest(ginContext, request, info)
	require.NoError(t, err)
	defer response.Body.Close()
	assert.Equal(t, http.StatusUnauthorized, response.StatusCode)
	firstCalls, _ := firstRecorder.snapshot()
	secondCalls, _ := secondRecorder.snapshot()
	assert.Equal(t, 1, firstCalls)
	assert.Equal(t, 0, secondCalls)
}

func TestDoRequestProxyPoolNetworkFailureSwitches(t *testing.T) {
	secondRecorder := &proxyRecorder{status: http.StatusOK}
	secondProxy := httptest.NewServer(secondRecorder.handler("second"))
	defer secondProxy.Close()

	ctx := context.Background()
	ginContext := newProxyPoolTestContext(t, ctx)
	request, closer := newReplayableProxyRequest(t, ctx, []byte(`{"model":"test"}`))
	defer closer.Close()
	info := newProxyPoolRelayInfo(20_002, []string{"http://127.0.0.1:1", secondProxy.URL}, nil)

	response, err := DoRequest(ginContext, request, info)
	require.NoError(t, err)
	defer response.Body.Close()
	assert.Equal(t, http.StatusOK, response.StatusCode)
	secondCalls, _ := secondRecorder.snapshot()
	assert.Equal(t, 1, secondCalls)
}

func TestDoRequestProxyPoolNetworkFailureCanBeDisabled(t *testing.T) {
	secondRecorder := &proxyRecorder{status: http.StatusOK}
	secondProxy := httptest.NewServer(secondRecorder.handler("second"))
	defer secondProxy.Close()

	ctx := context.Background()
	ginContext := newProxyPoolTestContext(t, ctx)
	request, closer := newReplayableProxyRequest(t, ctx, []byte(`{"model":"test"}`))
	defer closer.Close()
	info := newProxyPoolRelayInfo(20_003, []string{"http://127.0.0.1:1", secondProxy.URL}, nil)
	info.ChannelSetting.ProxyFailoverNetworkErrors = relayBool(false)

	response, err := DoRequest(ginContext, request, info)
	assert.Nil(t, response)
	require.Error(t, err)
	secondCalls, _ := secondRecorder.snapshot()
	assert.Equal(t, 0, secondCalls)
}

func TestDoRequestProxyPoolDoesNotReplayNonReplayableBody(t *testing.T) {
	firstRecorder := &proxyRecorder{status: http.StatusTooManyRequests}
	secondRecorder := &proxyRecorder{status: http.StatusOK}
	firstProxy := httptest.NewServer(firstRecorder.handler("first"))
	defer firstProxy.Close()
	secondProxy := httptest.NewServer(secondRecorder.handler("second"))
	defer secondProxy.Close()

	ctx := context.Background()
	ginContext := newProxyPoolTestContext(t, ctx)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://upstream.invalid/v1", struct{ io.Reader }{Reader: strings.NewReader("non-replayable")})
	require.NoError(t, err)
	require.Nil(t, request.GetBody)
	info := newProxyPoolRelayInfo(20_004, []string{firstProxy.URL, secondProxy.URL}, []int{429})

	response, err := DoRequest(ginContext, request, info)
	require.NoError(t, err)
	defer response.Body.Close()
	assert.Equal(t, http.StatusTooManyRequests, response.StatusCode)
	firstCalls, _ := firstRecorder.snapshot()
	secondCalls, _ := secondRecorder.snapshot()
	assert.Equal(t, 1, firstCalls)
	assert.Equal(t, 0, secondCalls)
}

func TestDoRequestProxyPoolCallerCancellationIsTerminal(t *testing.T) {
	secondRecorder := &proxyRecorder{status: http.StatusOK}
	secondProxy := httptest.NewServer(secondRecorder.handler("second"))
	defer secondProxy.Close()

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	ginContext := newProxyPoolTestContext(t, ctx)
	request, closer := newReplayableProxyRequest(t, ctx, []byte(`{"model":"test"}`))
	defer closer.Close()
	info := newProxyPoolRelayInfo(20_005, []string{"http://127.0.0.1:1", secondProxy.URL}, nil)

	response, err := DoRequest(ginContext, request, info)
	assert.Nil(t, response)
	require.Error(t, err)
	secondCalls, _ := secondRecorder.snapshot()
	assert.Equal(t, 0, secondCalls)
}
