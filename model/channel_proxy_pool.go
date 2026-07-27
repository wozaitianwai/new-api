package model

import (
	"fmt"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/dto"
)

func validateChannelProxyPoolSettings(settings *dto.ChannelSettings) error {
	if settings == nil || !settings.ProxyPoolEnabled {
		return nil
	}
	validProxyCount := 0
	for index, rawProxyURL := range settings.ProxyPool {
		if strings.TrimSpace(rawProxyURL) == "" {
			continue
		}
		if _, err := common.ParseProxyURLStrict(rawProxyURL); err != nil {
			return fmt.Errorf("invalid proxy pool entry %d: %w", index+1, err)
		}
		validProxyCount++
	}
	if validProxyCount == 0 {
		return fmt.Errorf("enabled proxy pool requires at least one valid proxy")
	}
	for _, statusCode := range settings.ProxyFailoverStatusCodes {
		if statusCode < 400 || statusCode > 599 {
			return fmt.Errorf("proxy failover status codes must be between 400 and 599")
		}
	}
	if settings.ProxyFailoverMaxAttempts < 0 || settings.ProxyFailoverMaxAttempts > 10 {
		return fmt.Errorf("proxy failover maximum attempts must be between 1 and 10")
	}
	if settings.ProxyCooldownSeconds != nil && (*settings.ProxyCooldownSeconds < 0 || *settings.ProxyCooldownSeconds > 3600) {
		return fmt.Errorf("proxy cooldown seconds must be between 0 and 3600")
	}
	return nil
}
