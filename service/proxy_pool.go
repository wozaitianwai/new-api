package service

import (
	"crypto/sha256"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/QuantumNous/new-api/relaykit/dto"
)

const (
	defaultProxyPoolAttempts        = 3
	maxProxyPoolAttempts            = 10
	defaultProxyPoolCooldownSeconds = 60
	maxProxyPoolCooldownSeconds     = 3600
)

type ProxyPoolAttemptPlan struct {
	ProxyURLs             []string
	FailoverNetworkErrors bool
	Cooldown              time.Duration
	Fingerprint           string
	statusCodes           map[int]struct{}
}

func (plan *ProxyPoolAttemptPlan) ShouldFailoverStatus(statusCode int) bool {
	if plan == nil {
		return false
	}
	_, ok := plan.statusCodes[statusCode]
	return ok
}

type normalizedProxyPoolConfig struct {
	proxyURLs             []string
	failoverNetworkErrors bool
	statusCodes           map[int]struct{}
	statusCodeList        []int
	maxAttempts           int
	cooldown              time.Duration
	fingerprint           string
}

type proxyPoolState struct {
	mutex         sync.Mutex
	fingerprint   string
	cursor        int
	cooldownUntil map[string]time.Time
}

type coolingProxy struct {
	proxyURL string
	until    time.Time
	order    int
}

var (
	proxyPoolStates sync.Map
	proxyPoolNow    = time.Now
)

func ValidateChannelProxySettings(settings dto.ChannelSettings) error {
	if !settings.ProxyPoolEnabled {
		return nil
	}
	_, err := normalizeProxyPoolConfig(settings, true)
	return err
}

func PrepareProxyPoolAttempts(channelID int, settings dto.ChannelSettings) (*ProxyPoolAttemptPlan, error) {
	if !settings.ProxyPoolEnabled {
		return nil, nil
	}
	config, err := normalizeProxyPoolConfig(settings, false)
	if err != nil {
		return nil, err
	}

	stateValue, _ := proxyPoolStates.LoadOrStore(channelID, &proxyPoolState{
		fingerprint:   config.fingerprint,
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
			if cooling[i].until.Equal(cooling[j].until) {
				return cooling[i].order < cooling[j].order
			}
			return cooling[i].until.Before(cooling[j].until)
		})
		candidates = make([]string, 0, len(cooling))
		for _, item := range cooling {
			candidates = append(candidates, item.proxyURL)
		}
	}
	if len(candidates) > config.maxAttempts {
		candidates = candidates[:config.maxAttempts]
	}

	return &ProxyPoolAttemptPlan{
		ProxyURLs:             append([]string(nil), candidates...),
		FailoverNetworkErrors: config.failoverNetworkErrors,
		Cooldown:              config.cooldown,
		Fingerprint:           config.fingerprint,
		statusCodes:           config.statusCodes,
	}, nil
}

func MarkProxyNetworkFailure(channelID int, fingerprint string, proxyURL string, cooldown time.Duration) {
	stateValue, ok := proxyPoolStates.Load(channelID)
	if !ok {
		return
	}
	state := stateValue.(*proxyPoolState)
	state.mutex.Lock()
	defer state.mutex.Unlock()
	if state.fingerprint != fingerprint {
		return
	}
	if cooldown <= 0 {
		delete(state.cooldownUntil, proxyURL)
		return
	}
	state.cooldownUntil[proxyURL] = proxyPoolNow().Add(cooldown)
}

func normalizeProxyPoolConfig(settings dto.ChannelSettings, strict bool) (*normalizedProxyPoolConfig, error) {
	proxyURLs := make([]string, 0, len(settings.ProxyPool))
	seenProxyURLs := make(map[string]struct{}, len(settings.ProxyPool))
	for index, rawProxyURL := range settings.ProxyPool {
		trimmedProxyURL := strings.TrimSpace(rawProxyURL)
		if trimmedProxyURL == "" {
			continue
		}
		if strict {
			if err := ValidateProxyURL(trimmedProxyURL); err != nil {
				return nil, fmt.Errorf("invalid proxy pool entry %d: %w", index+1, err)
			}
		}
		canonicalProxyURL, err := NormalizeProxyURL(trimmedProxyURL)
		if err != nil {
			return nil, fmt.Errorf("invalid proxy pool entry %d: %w", index+1, err)
		}
		if _, exists := seenProxyURLs[canonicalProxyURL]; exists {
			continue
		}
		seenProxyURLs[canonicalProxyURL] = struct{}{}
		proxyURLs = append(proxyURLs, canonicalProxyURL)
	}
	if len(proxyURLs) == 0 {
		return nil, fmt.Errorf("enabled proxy pool requires at least one valid proxy")
	}

	failoverNetworkErrors := true
	if settings.ProxyFailoverNetworkErrors != nil {
		failoverNetworkErrors = *settings.ProxyFailoverNetworkErrors
	}
	statusCodes := make(map[int]struct{}, len(settings.ProxyFailoverStatusCodes))
	statusCodeList := make([]int, 0, len(settings.ProxyFailoverStatusCodes))
	for _, statusCode := range settings.ProxyFailoverStatusCodes {
		if statusCode < 400 || statusCode > 599 {
			return nil, fmt.Errorf("proxy failover status codes must be between 400 and 599")
		}
		if _, exists := statusCodes[statusCode]; exists {
			continue
		}
		statusCodes[statusCode] = struct{}{}
		statusCodeList = append(statusCodeList, statusCode)
	}
	sort.Ints(statusCodeList)

	maxAttempts := settings.ProxyFailoverMaxAttempts
	if maxAttempts == 0 {
		maxAttempts = defaultProxyPoolAttempts
	}
	if maxAttempts < 1 || maxAttempts > maxProxyPoolAttempts {
		return nil, fmt.Errorf("proxy failover maximum attempts must be between 1 and 10")
	}
	if maxAttempts > len(proxyURLs) {
		maxAttempts = len(proxyURLs)
	}

	cooldownSeconds := defaultProxyPoolCooldownSeconds
	if settings.ProxyCooldownSeconds != nil {
		cooldownSeconds = *settings.ProxyCooldownSeconds
	}
	if cooldownSeconds < 0 || cooldownSeconds > maxProxyPoolCooldownSeconds {
		return nil, fmt.Errorf("proxy cooldown seconds must be between 0 and 3600")
	}
	cooldown := time.Duration(cooldownSeconds) * time.Second

	fingerprintInput := strings.Join(proxyURLs, "\x00") + fmt.Sprintf(
		"\x00network=%t\x00statuses=%v\x00attempts=%d\x00cooldown=%d",
		failoverNetworkErrors, statusCodeList, maxAttempts, cooldownSeconds,
	)
	fingerprint := fmt.Sprintf("%x", sha256.Sum256([]byte(fingerprintInput)))
	return &normalizedProxyPoolConfig{
		proxyURLs:             proxyURLs,
		failoverNetworkErrors: failoverNetworkErrors,
		statusCodes:           statusCodes,
		statusCodeList:        statusCodeList,
		maxAttempts:           maxAttempts,
		cooldown:              cooldown,
		fingerprint:           fingerprint,
	}, nil
}
