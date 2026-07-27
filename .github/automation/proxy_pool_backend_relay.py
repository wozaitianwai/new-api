from __future__ import annotations

from proxy_pool_patch_utils import gofmt, read, replace_once, replace_regex_once, run, write


def write_relay_tests() -> None:
    write(
        "relay/channel/api_request_proxy_pool_test.go",
        r'''package channel

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
	mutex sync.Mutex
	bodies [][]byte
	calls int
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
	for index := range recorder.bodies { bodies[index] = append([]byte(nil), recorder.bodies[index]...) }
	return recorder.calls, bodies
}

func relayBool(value bool) *bool { return &value }
func relayInt(value int) *int { return &value }

func newProxyPoolRelayInfo(channelID int, proxies []string, statusCodes []int) *relaycommon.RelayInfo {
	return &relaycommon.RelayInfo{
		ChannelMeta: &relaycommon.ChannelMeta{
			ChannelId: channelID,
			ChannelSetting: dto.ChannelSettings{
				ProxyPoolEnabled: true,
				ProxyPool: proxies,
				ProxyFailoverNetworkErrors: relayBool(true),
				ProxyFailoverStatusCodes: statusCodes,
				ProxyFailoverMaxAttempts: len(proxies),
				ProxyCooldownSeconds: relayInt(60),
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
''',
    )


def apply_relay_failover() -> None:
    constructor = "req, err := http.NewRequest(c.Request.Method, fullRequestURL, requestBody)"
    replacement = "req, err := http.NewRequestWithContext(c.Request.Context(), c.Request.Method, fullRequestURL, requestBody)"
    content = read("relay/channel/api_request.go")
    if content.count(constructor) != 3:
        raise RuntimeError(f"expected 3 request constructors, found {content.count(constructor)}")
    write("relay/channel/api_request.go", content.replace(constructor, replacement))

    marker = '''\tif err != nil {
\t\treturn nil, fmt.Errorf("new request failed: %w", err)
\t}
\tapplyUpstreamContentLength(req, info)'''
    replay_marker = '''\tif err != nil {
\t\treturn nil, fmt.Errorf("new request failed: %w", err)
\t}
\tcommon.AttachRequestBodyReplay(req, requestBody)
\tapplyUpstreamContentLength(req, info)'''
    content = read("relay/channel/api_request.go")
    if content.count(marker) != 3:
        raise RuntimeError(f"expected 3 request-body markers, found {content.count(marker)}")
    write("relay/channel/api_request.go", content.replace(marker, replay_marker))

    replace_once(
        "relay/channel/api_request.go",
        '''\treq.GetBody = func() (io.ReadCloser, error) {
\t\treturn io.NopCloser(requestBody), nil
\t}

''',
        "",
    )

    replace_regex_once(
        "relay/channel/api_request.go",
        r'''func doRequest\(c \*gin\.Context, req \*http\.Request, info \*common\.RelayInfo\) \(\*http\.Response, error\) \{.*?\n\}\n\nfunc DoTaskApiRequest''',
        r'''func doRequest(c *gin.Context, req *http.Request, info *common.RelayInfo) (*http.Response, error) {
	var stopPinger context.CancelFunc
	var pingerDone <-chan struct{}
	if info.IsStream {
		helper.SetEventStreamHeaders(c)
		generalSettings := operation_setting.GetGeneralSetting()
		if generalSettings.PingIntervalEnabled && !info.DisablePing {
			pingInterval := time.Duration(generalSettings.PingIntervalSeconds) * time.Second
			stopPinger, pingerDone = startPingKeepAlive(c, pingInterval)
			defer func() {
				if stopPinger != nil {
					stopPinger()
					<-pingerDone
					logger.LogDebug(c, "SSE ping goroutine stopped by defer")
				}
			}()
		}
	}

	if info == nil || info.ChannelMeta == nil || !info.ChannelSetting.ProxyPoolEnabled {
		var client *http.Client
		var err error
		if info != nil && info.ChannelMeta != nil && info.ChannelSetting.Proxy != "" {
			client, err = service.GetHttpClientWithProxy(info.ChannelSetting.Proxy)
			if err != nil { return nil, fmt.Errorf("new proxy http client failed: %w", err) }
		} else {
			client = service.GetHttpClient()
		}
		return executeOutboundRequest(c, client, req)
	}

	plan, err := service.PrepareProxyPoolAttempts(info.ChannelId, info.ChannelSetting)
	if err != nil { return nil, fmt.Errorf("prepare proxy pool failed: %w", err) }
	if plan == nil || len(plan.ProxyURLs) == 0 { return executeOutboundRequest(c, service.GetHttpClient(), req) }

	originalRequest := req
	for attemptIndex, proxyURL := range plan.ProxyURLs {
		attemptRequest, replayErr := requestForProxyAttempt(originalRequest, attemptIndex)
		if replayErr != nil {
			if attemptIndex == 0 { return nil, replayErr }
			break
		}
		client, clientErr := service.GetHttpClientWithProxy(proxyURL)
		if clientErr != nil { return nil, fmt.Errorf("new proxy http client failed: %w", clientErr) }

		resp, requestErr := client.Do(attemptRequest)
		if requestErr != nil {
			logger.LogError(c, "do request failed: "+requestErr.Error())
			if requestContextDone(c, attemptRequest) { return nil, newOutboundRequestError(requestErr) }
			if plan.FailoverNetworkErrors {
				service.MarkProxyNetworkFailure(info.ChannelId, plan.Fingerprint, proxyURL, plan.Cooldown)
			}
			if !plan.FailoverNetworkErrors || attemptIndex+1 >= len(plan.ProxyURLs) || !requestCanReplay(originalRequest) {
				return nil, newOutboundRequestError(requestErr)
			}
			logger.LogDebug(c, "proxy pool network failover: channel_id=%d attempt=%d/%d proxy=%s", info.ChannelId, attemptIndex+1, len(plan.ProxyURLs), sanitizeProxyEndpoint(proxyURL))
			continue
		}
		if resp == nil { return nil, errors.New("resp is nil") }
		if plan.ShouldFailoverStatus(resp.StatusCode) && attemptIndex+1 < len(plan.ProxyURLs) && requestCanReplay(originalRequest) {
			_ = resp.Body.Close()
			logger.LogDebug(c, "proxy pool status failover: channel_id=%d attempt=%d/%d proxy=%s status=%d", info.ChannelId, attemptIndex+1, len(plan.ProxyURLs), sanitizeProxyEndpoint(proxyURL), resp.StatusCode)
			continue
		}
		return finalizeOutboundResponse(c, attemptRequest, resp)
	}
	return nil, newOutboundRequestError(errors.New("proxy pool exhausted without a response"))
}

func executeOutboundRequest(c *gin.Context, client *http.Client, req *http.Request) (*http.Response, error) {
	resp, err := client.Do(req)
	if err != nil {
		logger.LogError(c, "do request failed: "+err.Error())
		return nil, newOutboundRequestError(err)
	}
	if resp == nil { return nil, errors.New("resp is nil") }
	return finalizeOutboundResponse(c, req, resp)
}

func finalizeOutboundResponse(c *gin.Context, req *http.Request, resp *http.Response) (*http.Response, error) {
	if upID := resp.Header.Get(common2.RequestIdKey); upID != "" { c.Set(common2.UpstreamRequestIdKey, upID) }
	if req.Body != nil { _ = req.Body.Close() }
	if c != nil && c.Request != nil && c.Request.Body != nil { _ = c.Request.Body.Close() }
	return resp, nil
}

func newOutboundRequestError(err error) error {
	return types.NewError(err, types.ErrorCodeDoRequestFailed, types.ErrOptionWithHideErrMsg("upstream error: do request failed"))
}

func requestForProxyAttempt(original *http.Request, attemptIndex int) (*http.Request, error) {
	if attemptIndex == 0 { return original, nil }
	if original.GetBody == nil { return nil, errors.New("upstream request body cannot be replayed") }
	body, err := original.GetBody()
	if err != nil { return nil, fmt.Errorf("recreate upstream request body: %w", err) }
	cloned := original.Clone(original.Context())
	cloned.Body = body
	cloned.GetBody = original.GetBody
	cloned.ContentLength = original.ContentLength
	return cloned, nil
}

func requestCanReplay(req *http.Request) bool {
	if req == nil || req.Body == nil || req.Body == http.NoBody { return true }
	return req.GetBody != nil
}

func requestContextDone(c *gin.Context, req *http.Request) bool {
	if req != nil && req.Context().Err() != nil { return true }
	return c != nil && c.Request != nil && c.Request.Context().Err() != nil
}

func sanitizeProxyEndpoint(rawProxyURL string) string {
	parsedURL, err := url.Parse(rawProxyURL)
	if err != nil { return "invalid-proxy" }
	return parsedURL.Scheme + "://" + parsedURL.Host
}

func DoTaskApiRequest''',
    )
    replace_once(
        "relay/channel/api_request.go",
        '''\t"net/http"
\t"regexp"''',
        '''\t"net/http"
\t"net/url"
\t"regexp"''',
    )


def execute_relay() -> None:
    write_relay_tests()
    run(["go", "test", "./relay/channel", "-run", "TestDoRequestProxyPool", "-count=1"], expect_failure=True)
    apply_relay_failover()
    gofmt("relay/channel/api_request.go", "relay/channel/api_request_proxy_pool_test.go")
    run(["go", "test", "./relay/channel", "-run", "TestDoRequestProxyPool", "-count=1"])
