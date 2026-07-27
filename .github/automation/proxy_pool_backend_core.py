from __future__ import annotations

from proxy_pool_patch_utils import gofmt, replace_once, run, write


def write_service_tests() -> None:
    write(
        "service/proxy_pool_test.go",
        r'''package service

import (
	"sync"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/dto"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func proxyPoolBool(value bool) *bool { return &value }
func proxyPoolInt(value int) *int { return &value }

func resetProxyPoolTests() {
	proxyPoolStates = sync.Map{}
	proxyPoolNow = time.Now
}

func proxyPoolTestSettings() dto.ChannelSettings {
	return dto.ChannelSettings{
		ProxyPoolEnabled:           true,
		ProxyPool:                  []string{"http://127.0.0.1:18080", "socks5://127.0.0.1:1080"},
		ProxyFailoverNetworkErrors: proxyPoolBool(true),
		ProxyFailoverStatusCodes:   []int{429, 502, 503, 504},
		ProxyFailoverMaxAttempts:   2,
		ProxyCooldownSeconds:       proxyPoolInt(60),
	}
}

func TestPrepareProxyPoolAttemptsRotatesPerChannel(t *testing.T) {
	resetProxyPoolTests()
	settings := proxyPoolTestSettings()

	first, err := PrepareProxyPoolAttempts(101, settings)
	require.NoError(t, err)
	second, err := PrepareProxyPoolAttempts(101, settings)
	require.NoError(t, err)

	assert.Equal(t, []string{"http://127.0.0.1:18080", "socks5://127.0.0.1:1080"}, first.ProxyURLs)
	assert.Equal(t, []string{"socks5://127.0.0.1:1080", "http://127.0.0.1:18080"}, second.ProxyURLs)
}

func TestPrepareProxyPoolAttemptsIsConcurrentSafe(t *testing.T) {
	resetProxyPoolTests()
	settings := dto.ChannelSettings{
		ProxyPoolEnabled:           true,
		ProxyPool:                  []string{"http://127.0.0.1:18080", "http://127.0.0.1:18081", "http://127.0.0.1:18082"},
		ProxyFailoverNetworkErrors: proxyPoolBool(true),
		ProxyFailoverMaxAttempts:   1,
		ProxyCooldownSeconds:       proxyPoolInt(60),
	}

	results := make(chan string, 30)
	var waitGroup sync.WaitGroup
	for range 30 {
		waitGroup.Add(1)
		go func() {
			defer waitGroup.Done()
			plan, err := PrepareProxyPoolAttempts(102, settings)
			require.NoError(t, err)
			results <- plan.ProxyURLs[0]
		}()
	}
	waitGroup.Wait()
	close(results)

	counts := map[string]int{}
	for proxyURL := range results { counts[proxyURL]++ }
	assert.Equal(t, 10, counts["http://127.0.0.1:18080"])
	assert.Equal(t, 10, counts["http://127.0.0.1:18081"])
	assert.Equal(t, 10, counts["http://127.0.0.1:18082"])
}

func TestPrepareProxyPoolAttemptsSkipsCoolingProxy(t *testing.T) {
	resetProxyPoolTests()
	current := time.Unix(1_700_000_000, 0)
	proxyPoolNow = func() time.Time { return current }
	settings := proxyPoolTestSettings()

	first, err := PrepareProxyPoolAttempts(103, settings)
	require.NoError(t, err)
	MarkProxyNetworkFailure(103, first.Fingerprint, first.ProxyURLs[0], time.Minute)

	second, err := PrepareProxyPoolAttempts(103, settings)
	require.NoError(t, err)
	assert.Equal(t, []string{"socks5://127.0.0.1:1080"}, second.ProxyURLs)

	current = current.Add(2 * time.Minute)
	third, err := PrepareProxyPoolAttempts(103, settings)
	require.NoError(t, err)
	assert.Len(t, third.ProxyURLs, 2)
	assert.Contains(t, third.ProxyURLs, "http://127.0.0.1:18080")
}

func TestPrepareProxyPoolAttemptsUsesEarliestWhenAllCooling(t *testing.T) {
	resetProxyPoolTests()
	current := time.Unix(1_700_000_000, 0)
	proxyPoolNow = func() time.Time { return current }
	settings := proxyPoolTestSettings()

	plan, err := PrepareProxyPoolAttempts(104, settings)
	require.NoError(t, err)
	MarkProxyNetworkFailure(104, plan.Fingerprint, "http://127.0.0.1:18080", 5*time.Minute)
	MarkProxyNetworkFailure(104, plan.Fingerprint, "socks5://127.0.0.1:1080", time.Minute)

	next, err := PrepareProxyPoolAttempts(104, settings)
	require.NoError(t, err)
	require.NotEmpty(t, next.ProxyURLs)
	assert.Equal(t, "socks5://127.0.0.1:1080", next.ProxyURLs[0])
}

func TestPrepareProxyPoolAttemptsResetsOnConfigurationChange(t *testing.T) {
	resetProxyPoolTests()
	settings := proxyPoolTestSettings()
	first, err := PrepareProxyPoolAttempts(105, settings)
	require.NoError(t, err)
	_, err = PrepareProxyPoolAttempts(105, settings)
	require.NoError(t, err)

	settings.ProxyPool = []string{"http://127.0.0.1:19080", "http://127.0.0.1:19081"}
	changed, err := PrepareProxyPoolAttempts(105, settings)
	require.NoError(t, err)
	assert.NotEqual(t, first.Fingerprint, changed.Fingerprint)
	assert.Equal(t, "http://127.0.0.1:19080", changed.ProxyURLs[0])
}

func TestPrepareProxyPoolAttemptsNormalizesDuplicatesAndDefaults(t *testing.T) {
	resetProxyPoolTests()
	settings := dto.ChannelSettings{
		ProxyPoolEnabled: true,
		ProxyPool: []string{" socks5://127.0.0.1 ", "socks5://127.0.0.1:1080", "", "http://127.0.0.1:18080"},
	}
	plan, err := PrepareProxyPoolAttempts(106, settings)
	require.NoError(t, err)
	assert.Equal(t, []string{"socks5://127.0.0.1:1080", "http://127.0.0.1:18080"}, plan.ProxyURLs)
	assert.True(t, plan.FailoverNetworkErrors)
	assert.Equal(t, time.Minute, plan.Cooldown)
}

func TestProxyPoolStatusLookupIsConfigurable(t *testing.T) {
	resetProxyPoolTests()
	settings := proxyPoolTestSettings()
	settings.ProxyFailoverStatusCodes = []int{400, 401, 403, 404, 429}
	plan, err := PrepareProxyPoolAttempts(107, settings)
	require.NoError(t, err)
	for _, statusCode := range []int{400, 401, 403, 404, 429} { assert.True(t, plan.ShouldFailoverStatus(statusCode)) }
	assert.False(t, plan.ShouldFailoverStatus(502))
}

func TestValidateChannelProxySettings(t *testing.T) {
	valid := proxyPoolTestSettings()
	require.NoError(t, ValidateChannelProxySettings(valid))

	testCases := []struct {
		name string
		mutate func(*dto.ChannelSettings)
		contains string
	}{
		{"missing proxy", func(settings *dto.ChannelSettings) { settings.ProxyPool = nil }, "at least one"},
		{"invalid proxy URL", func(settings *dto.ChannelSettings) { settings.ProxyPool = []string{"ftp://127.0.0.1:21"} }, "proxy"},
		{"invalid status", func(settings *dto.ChannelSettings) { settings.ProxyFailoverStatusCodes = []int{399} }, "400 and 599"},
		{"too many attempts", func(settings *dto.ChannelSettings) { settings.ProxyFailoverMaxAttempts = 11 }, "between 1 and 10"},
		{"negative cooldown", func(settings *dto.ChannelSettings) { settings.ProxyCooldownSeconds = proxyPoolInt(-1) }, "between 0 and 3600"},
	}
	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			settings := valid
			settings.ProxyPool = append([]string(nil), valid.ProxyPool...)
			settings.ProxyFailoverStatusCodes = append([]int(nil), valid.ProxyFailoverStatusCodes...)
			testCase.mutate(&settings)
			err := ValidateChannelProxySettings(settings)
			require.Error(t, err)
			assert.Contains(t, err.Error(), testCase.contains)
		})
	}

	disabled := dto.ChannelSettings{ProxyPoolEnabled: false, ProxyPool: []string{"not a URL"}}
	require.NoError(t, ValidateChannelProxySettings(disabled))
}
''',
    )


def apply_settings_and_selector() -> None:
    replace_once(
        "dto/channel_settings.go",
        '''type ChannelSettings struct {
\tForceFormat            bool   `json:"force_format,omitempty"`
\tThinkingToContent      bool   `json:"thinking_to_content,omitempty"`
\tProxy                  string `json:"proxy"`
\tPassThroughBodyEnabled bool   `json:"pass_through_body_enabled,omitempty"`
\tSystemPrompt           string `json:"system_prompt,omitempty"`
\tSystemPromptOverride   bool   `json:"system_prompt_override,omitempty"`
}''',
        '''type ChannelSettings struct {
\tForceFormat                bool     `json:"force_format,omitempty"`
\tThinkingToContent          bool     `json:"thinking_to_content,omitempty"`
\tProxy                      string   `json:"proxy"`
\tProxyPoolEnabled           bool     `json:"proxy_pool_enabled,omitempty"`
\tProxyPool                  []string `json:"proxy_pool,omitempty"`
\tProxyFailoverNetworkErrors *bool    `json:"proxy_failover_network_errors,omitempty"`
\tProxyFailoverStatusCodes   []int    `json:"proxy_failover_status_codes,omitempty"`
\tProxyFailoverMaxAttempts   int      `json:"proxy_failover_max_attempts,omitempty"`
\tProxyCooldownSeconds       *int     `json:"proxy_cooldown_seconds,omitempty"`
\tPassThroughBodyEnabled     bool     `json:"pass_through_body_enabled,omitempty"`
\tSystemPrompt               string   `json:"system_prompt,omitempty"`
\tSystemPromptOverride       bool     `json:"system_prompt_override,omitempty"`
}''',
    )
    write(
        "service/proxy_pool.go",
        r'''package service

import (
	"crypto/sha256"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/QuantumNous/new-api/dto"
)

const (
	defaultProxyPoolAttempts = 3
	maxProxyPoolAttempts = 10
	defaultProxyPoolCooldownSeconds = 60
	maxProxyPoolCooldownSeconds = 3600
)

type ProxyPoolAttemptPlan struct {
	ProxyURLs []string
	FailoverNetworkErrors bool
	Cooldown time.Duration
	Fingerprint string
	statusCodes map[int]struct{}
}

func (plan *ProxyPoolAttemptPlan) ShouldFailoverStatus(statusCode int) bool {
	if plan == nil { return false }
	_, ok := plan.statusCodes[statusCode]
	return ok
}

type normalizedProxyPoolConfig struct {
	proxyURLs []string
	failoverNetworkErrors bool
	statusCodes map[int]struct{}
	statusCodeList []int
	maxAttempts int
	cooldown time.Duration
	fingerprint string
}

type proxyPoolState struct {
	mutex sync.Mutex
	fingerprint string
	cursor int
	cooldownUntil map[string]time.Time
}

type coolingProxy struct { proxyURL string; until time.Time; order int }

var (
	proxyPoolStates sync.Map
	proxyPoolNow = time.Now
)

func ValidateChannelProxySettings(settings dto.ChannelSettings) error {
	if !settings.ProxyPoolEnabled { return nil }
	_, err := normalizeProxyPoolConfig(settings, true)
	return err
}

func PrepareProxyPoolAttempts(channelID int, settings dto.ChannelSettings) (*ProxyPoolAttemptPlan, error) {
	if !settings.ProxyPoolEnabled { return nil, nil }
	config, err := normalizeProxyPoolConfig(settings, false)
	if err != nil { return nil, err }

	stateValue, _ := proxyPoolStates.LoadOrStore(channelID, &proxyPoolState{
		fingerprint: config.fingerprint,
		cooldownUntil: make(map[string]time.Time),
	})
	state := stateValue.(*proxyPoolState)
	state.mutex.Lock()
	defer state.mutex.Unlock()

	if state.fingerprint != config.fingerprint {
		state.fingerprint = config.fingerprint
		state.cursor = 0
		state.cooldownUntil = make(map[string]time.Time)
	}

	now := proxyPoolNow()
	start := state.cursor % len(config.proxyURLs)
	state.cursor = (state.cursor + 1) % len(config.proxyURLs)
	healthy := make([]string, 0, config.maxAttempts)
	cooling := make([]coolingProxy, 0, len(config.proxyURLs))
	for offset := 0; offset < len(config.proxyURLs); offset++ {
		index := (start + offset) % len(config.proxyURLs)
		proxyURL := config.proxyURLs[index]
		until, coolingDown := state.cooldownUntil[proxyURL]
		if !coolingDown || !until.After(now) {
			delete(state.cooldownUntil, proxyURL)
			healthy = append(healthy, proxyURL)
			continue
		}
		cooling = append(cooling, coolingProxy{proxyURL: proxyURL, until: until, order: offset})
	}

	candidates := healthy
	if len(candidates) == 0 {
		sort.SliceStable(cooling, func(i, j int) bool {
			if cooling[i].until.Equal(cooling[j].until) { return cooling[i].order < cooling[j].order }
			return cooling[i].until.Before(cooling[j].until)
		})
		candidates = make([]string, 0, len(cooling))
		for _, item := range cooling { candidates = append(candidates, item.proxyURL) }
	}
	if len(candidates) > config.maxAttempts { candidates = candidates[:config.maxAttempts] }

	return &ProxyPoolAttemptPlan{
		ProxyURLs: append([]string(nil), candidates...),
		FailoverNetworkErrors: config.failoverNetworkErrors,
		Cooldown: config.cooldown,
		Fingerprint: config.fingerprint,
		statusCodes: config.statusCodes,
	}, nil
}

func MarkProxyNetworkFailure(channelID int, fingerprint string, proxyURL string, cooldown time.Duration) {
	stateValue, ok := proxyPoolStates.Load(channelID)
	if !ok { return }
	state := stateValue.(*proxyPoolState)
	state.mutex.Lock()
	defer state.mutex.Unlock()
	if state.fingerprint != fingerprint { return }
	if cooldown <= 0 { delete(state.cooldownUntil, proxyURL); return }
	state.cooldownUntil[proxyURL] = proxyPoolNow().Add(cooldown)
}

func normalizeProxyPoolConfig(settings dto.ChannelSettings, strict bool) (*normalizedProxyPoolConfig, error) {
	proxyURLs := make([]string, 0, len(settings.ProxyPool))
	seenProxyURLs := make(map[string]struct{}, len(settings.ProxyPool))
	for index, rawProxyURL := range settings.ProxyPool {
		trimmedProxyURL := strings.TrimSpace(rawProxyURL)
		if trimmedProxyURL == "" { continue }
		if strict {
			if err := ValidateProxyURL(trimmedProxyURL); err != nil {
				return nil, fmt.Errorf("invalid proxy pool entry %d: %w", index+1, err)
			}
		}
		canonicalProxyURL, err := NormalizeProxyURL(trimmedProxyURL)
		if err != nil { return nil, fmt.Errorf("invalid proxy pool entry %d: %w", index+1, err) }
		if _, exists := seenProxyURLs[canonicalProxyURL]; exists { continue }
		seenProxyURLs[canonicalProxyURL] = struct{}{}
		proxyURLs = append(proxyURLs, canonicalProxyURL)
	}
	if len(proxyURLs) == 0 { return nil, fmt.Errorf("enabled proxy pool requires at least one valid proxy") }

	failoverNetworkErrors := true
	if settings.ProxyFailoverNetworkErrors != nil { failoverNetworkErrors = *settings.ProxyFailoverNetworkErrors }
	statusCodes := make(map[int]struct{}, len(settings.ProxyFailoverStatusCodes))
	statusCodeList := make([]int, 0, len(settings.ProxyFailoverStatusCodes))
	for _, statusCode := range settings.ProxyFailoverStatusCodes {
		if statusCode < 400 || statusCode > 599 { return nil, fmt.Errorf("proxy failover status codes must be between 400 and 599") }
		if _, exists := statusCodes[statusCode]; exists { continue }
		statusCodes[statusCode] = struct{}{}
		statusCodeList = append(statusCodeList, statusCode)
	}
	sort.Ints(statusCodeList)

	maxAttempts := settings.ProxyFailoverMaxAttempts
	if maxAttempts == 0 { maxAttempts = defaultProxyPoolAttempts }
	if maxAttempts < 1 || maxAttempts > maxProxyPoolAttempts { return nil, fmt.Errorf("proxy failover maximum attempts must be between 1 and 10") }
	if maxAttempts > len(proxyURLs) { maxAttempts = len(proxyURLs) }

	cooldownSeconds := defaultProxyPoolCooldownSeconds
	if settings.ProxyCooldownSeconds != nil { cooldownSeconds = *settings.ProxyCooldownSeconds }
	if cooldownSeconds < 0 || cooldownSeconds > maxProxyPoolCooldownSeconds { return nil, fmt.Errorf("proxy cooldown seconds must be between 0 and 3600") }
	cooldown := time.Duration(cooldownSeconds) * time.Second

	fingerprintInput := strings.Join(proxyURLs, "\x00") + fmt.Sprintf(
		"\x00network=%t\x00statuses=%v\x00attempts=%d\x00cooldown=%d",
		failoverNetworkErrors, statusCodeList, maxAttempts, cooldownSeconds,
	)
	fingerprint := fmt.Sprintf("%x", sha256.Sum256([]byte(fingerprintInput)))
	return &normalizedProxyPoolConfig{
		proxyURLs: proxyURLs,
		failoverNetworkErrors: failoverNetworkErrors,
		statusCodes: statusCodes,
		statusCodeList: statusCodeList,
		maxAttempts: maxAttempts,
		cooldown: cooldown,
		fingerprint: fingerprint,
	}, nil
}
''',
    )


def write_outbound_body_test() -> None:
    write(
        "relay/common/outbound_body_test.go",
        r'''package common

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
''',
    )


def apply_outbound_body_replay() -> None:
    write(
        "relay/common/outbound_body.go",
        r'''package common

import (
	"io"
	"net/http"

	rootcommon "github.com/QuantumNous/new-api/common"
)

type RequestBodyReplayer interface {
	NewRequestBody() (io.ReadCloser, error)
}

type replayableBody struct { storage rootcommon.BodyStorage }

func (body *replayableBody) Read(buffer []byte) (int, error) { return body.storage.Read(buffer) }

func (body *replayableBody) NewRequestBody() (io.ReadCloser, error) {
	if _, err := body.storage.Seek(0, io.SeekStart); err != nil { return nil, err }
	return io.NopCloser(rootcommon.ReaderOnly(body.storage)), nil
}

// AttachRequestBodyReplay configures req.GetBody when body knows how to rewind
// itself. Existing net/http GetBody implementations are preserved.
func AttachRequestBodyReplay(req *http.Request, body io.Reader) {
	if req == nil || req.GetBody != nil { return }
	if body == nil {
		req.GetBody = func() (io.ReadCloser, error) { return http.NoBody, nil }
		return
	}
	replayer, ok := body.(RequestBodyReplayer)
	if !ok { return }
	req.GetBody = replayer.NewRequestBody
}

// NewOutboundJSONBody wraps the already-marshaled upstream request body into a
// BodyStorage. The caller must close the returned closer after the upstream call.
func NewOutboundJSONBody(data []byte) (body io.Reader, size int64, closer io.Closer, err error) {
	storage, err := rootcommon.CreateBodyStorage(data)
	if err != nil { return nil, 0, nil, err }
	return &replayableBody{storage: storage}, storage.Size(), storage, nil
}
''',
    )


def write_model_validation_test() -> None:
    write(
        "model/channel_proxy_pool_test.go",
        r'''package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/dto"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func channelWithProxySettings(t *testing.T, settings dto.ChannelSettings) *Channel {
	data, err := common.Marshal(settings)
	require.NoError(t, err)
	setting := string(data)
	return &Channel{Setting: &setting}
}

func proxyPoolIntPointer(value int) *int { return &value }

func TestChannelValidateSettingsAcceptsProxyPool(t *testing.T) {
	channel := channelWithProxySettings(t, dto.ChannelSettings{
		ProxyPoolEnabled: true,
		ProxyPool: []string{"http://127.0.0.1:18080", "socks5://127.0.0.1:1080"},
		ProxyFailoverStatusCodes: []int{400, 401, 403, 404, 429, 502, 503, 504},
		ProxyFailoverMaxAttempts: 2,
		ProxyCooldownSeconds: proxyPoolIntPointer(60),
	})
	require.NoError(t, channel.ValidateSettings())
}

func TestChannelValidateSettingsRejectsInvalidProxyPool(t *testing.T) {
	testCases := []struct { name string; settings dto.ChannelSettings; contains string }{
		{"empty enabled pool", dto.ChannelSettings{ProxyPoolEnabled: true}, "at least one"},
		{"invalid URL", dto.ChannelSettings{ProxyPoolEnabled: true, ProxyPool: []string{"http://127.0.0.1:8080/path"}}, "invalid proxy pool entry"},
		{"invalid status", dto.ChannelSettings{ProxyPoolEnabled: true, ProxyPool: []string{"http://127.0.0.1:18080"}, ProxyFailoverStatusCodes: []int{600}}, "400 and 599"},
		{"invalid attempts", dto.ChannelSettings{ProxyPoolEnabled: true, ProxyPool: []string{"http://127.0.0.1:18080"}, ProxyFailoverMaxAttempts: 11}, "between 1 and 10"},
		{"invalid cooldown", dto.ChannelSettings{ProxyPoolEnabled: true, ProxyPool: []string{"http://127.0.0.1:18080"}, ProxyCooldownSeconds: proxyPoolIntPointer(3601)}, "between 0 and 3600"},
	}
	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			err := channelWithProxySettings(t, testCase.settings).ValidateSettings()
			require.Error(t, err)
			assert.Contains(t, err.Error(), testCase.contains)
		})
	}
}

func TestChannelValidateSettingsIgnoresDisabledPoolValues(t *testing.T) {
	channel := channelWithProxySettings(t, dto.ChannelSettings{ProxyPoolEnabled: false, ProxyPool: []string{"not a URL"}})
	require.NoError(t, channel.ValidateSettings())
}
''',
    )


def apply_model_validation() -> None:
    replace_once(
        "model/channel.go",
        '''\tif _, err := common.ParseProxyURLStrict(channelParams.Proxy); err != nil {
\t\treturn fmt.Errorf("invalid channel proxy: %w", err)
\t}''',
        '''\tif _, err := common.ParseProxyURLStrict(channelParams.Proxy); err != nil {
\t\treturn fmt.Errorf("invalid channel proxy: %w", err)
\t}
\tif err := validateChannelProxyPoolSettings(channelParams); err != nil {
\t\treturn err
\t}''',
    )
    write(
        "model/channel_proxy_pool.go",
        r'''package model

import (
	"fmt"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/dto"
)

func validateChannelProxyPoolSettings(settings *dto.ChannelSettings) error {
	if settings == nil || !settings.ProxyPoolEnabled { return nil }
	validProxyCount := 0
	for index, rawProxyURL := range settings.ProxyPool {
		if strings.TrimSpace(rawProxyURL) == "" { continue }
		if _, err := common.ParseProxyURLStrict(rawProxyURL); err != nil {
			return fmt.Errorf("invalid proxy pool entry %d: %w", index+1, err)
		}
		validProxyCount++
	}
	if validProxyCount == 0 { return fmt.Errorf("enabled proxy pool requires at least one valid proxy") }
	for _, statusCode := range settings.ProxyFailoverStatusCodes {
		if statusCode < 400 || statusCode > 599 { return fmt.Errorf("proxy failover status codes must be between 400 and 599") }
	}
	if settings.ProxyFailoverMaxAttempts < 0 || settings.ProxyFailoverMaxAttempts > 10 {
		return fmt.Errorf("proxy failover maximum attempts must be between 1 and 10")
	}
	if settings.ProxyCooldownSeconds != nil && (*settings.ProxyCooldownSeconds < 0 || *settings.ProxyCooldownSeconds > 3600) {
		return fmt.Errorf("proxy cooldown seconds must be between 0 and 3600")
	}
	return nil
}
''',
    )


def execute_core() -> None:
    write_service_tests()
    run(["go", "test", "./service", "-run", "Test(PrepareProxyPool|ProxyPool|ValidateChannelProxy)", "-count=1"], expect_failure=True)
    apply_settings_and_selector()
    gofmt("dto/channel_settings.go", "service/proxy_pool.go", "service/proxy_pool_test.go")
    run(["go", "test", "./service", "-run", "Test(PrepareProxyPool|ProxyPool|ValidateChannelProxy)", "-count=1"])

    write_outbound_body_test()
    run(["go", "test", "./relay/common", "-run", "TestOutboundJSONBody", "-count=1"], expect_failure=True)
    apply_outbound_body_replay()
    gofmt("relay/common/outbound_body.go", "relay/common/outbound_body_test.go")
    run(["go", "test", "./relay/common", "-run", "TestOutboundJSONBody", "-count=1"])

    write_model_validation_test()
    run(["go", "test", "./model", "-run", "TestChannelValidateSettings.*ProxyPool", "-count=1"], expect_failure=True)
    apply_model_validation()
    gofmt("model/channel.go", "model/channel_proxy_pool.go", "model/channel_proxy_pool_test.go")
    run(["go", "test", "./model", "-run", "TestChannelValidateSettings.*ProxyPool", "-count=1"])
