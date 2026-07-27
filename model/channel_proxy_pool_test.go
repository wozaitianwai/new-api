package model

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
		ProxyPoolEnabled:         true,
		ProxyPool:                []string{"http://127.0.0.1:18080", "socks5://127.0.0.1:1080"},
		ProxyFailoverStatusCodes: []int{400, 401, 403, 404, 429, 502, 503, 504},
		ProxyFailoverMaxAttempts: 2,
		ProxyCooldownSeconds:     proxyPoolIntPointer(60),
	})
	require.NoError(t, channel.ValidateSettings())
}

func TestChannelValidateSettingsRejectsInvalidProxyPool(t *testing.T) {
	testCases := []struct {
		name     string
		settings dto.ChannelSettings
		contains string
	}{
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
