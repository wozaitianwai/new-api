package service

import (
	"sync"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/relaykit/dto"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func proxyPoolBool(value bool) *bool { return &value }
func proxyPoolInt(value int) *int    { return &value }

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
	for proxyURL := range results {
		counts[proxyURL]++
	}
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
		ProxyPool:        []string{" socks5://127.0.0.1 ", "socks5://127.0.0.1:1080", "", "http://127.0.0.1:18080"},
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
	for _, statusCode := range []int{400, 401, 403, 404, 429} {
		assert.True(t, plan.ShouldFailoverStatus(statusCode))
	}
	assert.False(t, plan.ShouldFailoverStatus(502))
}

func TestValidateChannelProxySettings(t *testing.T) {
	valid := proxyPoolTestSettings()
	require.NoError(t, ValidateChannelProxySettings(valid))

	testCases := []struct {
		name     string
		mutate   func(*dto.ChannelSettings)
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
