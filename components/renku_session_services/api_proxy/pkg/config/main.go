package config

import (
	"fmt"
	"net/url"
	"reflect"

	"github.com/mitchellh/mapstructure"
	"github.com/spf13/viper"
)

type Config struct {
	Host              string         `mapstructure:"host"`
	Port              int            `mapstructure:"port"`
	SessionID         string         `mapstructure:"session_id"`
	RenkuAccessToken  RedactedString `mapstructure:"renku_access_token"`
	RenkuRefreshToken RedactedString `mapstructure:"renku_refresh_token"`
	RenkuRealm        string         `mapstructure:"renku_realm"`
	RenkuClientID     string         `mapstructure:"renku_client_id"`
	RenkuClientSecret RedactedString `mapstructure:"renku_client_secret"`
	RenkuURL          *url.URL       `mapstructure:"renku_url"`
}

func LoadAndValidateConfig() (config Config, err error) {
	config, err = loadConfig()
	if err != nil {
		return Config{}, err
	}
	err = config.Validate()
	if err != nil {
		return Config{}, err
	}
	return config, nil
}

func loadConfig() (config Config, err error) {
	v := viper.New()
	v.SetConfigType("env")
	v.SetEnvPrefix("api_proxy")
	v.AutomaticEnv()

	v.SetDefault("host", "")
	v.SetDefault("port", 58080)
	v.SetDefault("session_id", "")
	v.SetDefault("renku_access_token", "")
	v.SetDefault("renku_refresh_token", "")
	v.SetDefault("renku_realm", "")
	v.SetDefault("renku_client_id", "")
	v.SetDefault("renku_client_secret", "")
	v.SetDefault("renku_url", nil)

	dh := viper.DecodeHook(parseStringAsURL())
	err = v.Unmarshal(&config, dh)
	if err != nil {
		return Config{}, err
	}
	return config, nil
}

func (c *Config) Validate() error {
	if c.SessionID == "" {
		return fmt.Errorf("the session ID is not defined")
	}
	if c.RenkuAccessToken == "" {
		return fmt.Errorf("the renku access token is not defined")
	}
	if c.RenkuRefreshToken == "" {
		return fmt.Errorf("the renku refresh token is not defined")
	}
	if c.RenkuURL == nil {
		return fmt.Errorf("the renku URL is not defined")
	}
	if c.RenkuRealm == "" {
		return fmt.Errorf("the renku realm is not defined")
	}
	if c.RenkuClientID == "" {
		return fmt.Errorf("the renku client id is not defined")
	}
	if c.RenkuClientSecret == "" {
		return fmt.Errorf("the renku client secret is not defined")
	}
	return nil
}

func parseStringAsURL() mapstructure.DecodeHookFuncType {
	return func(f reflect.Type, t reflect.Type, data any) (interface{}, error) {
		// Check that the data is string
		if f.Kind() != reflect.String {
			return data, nil
		}

		// Check that the target type is our custom type
		if t != reflect.TypeOf(url.URL{}) {
			return data, nil
		}

		// Return the parsed value
		dataStr, ok := data.(string)
		if !ok {
			return nil, fmt.Errorf("cannot cast URL value to string")
		}
		if dataStr == "" {
			return nil, fmt.Errorf("empty values are not allowed for URLs")
		}
		url, err := url.Parse(dataStr)
		if err != nil {
			return nil, err
		}
		return url, nil
	}
}
