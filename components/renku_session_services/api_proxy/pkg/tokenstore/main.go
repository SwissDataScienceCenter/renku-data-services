package tokenstore

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/config"
	"github.com/golang-jwt/jwt/v5"
)

type TokenStore struct {
	Config               *config.Config
	renkuAccessToken     string
	renkuRefreshToken    string
	renkuAccessTokenLock *sync.RWMutex
}

func New(c *config.Config) *TokenStore {
	store := TokenStore{
		Config:               c,
		renkuAccessToken:     string(c.RenkuAccessToken),
		renkuRefreshToken:    string(c.RenkuRefreshToken),
		renkuAccessTokenLock: &sync.RWMutex{},
	}
	return &store
}

func (s *TokenStore) GetValidRenkuAccessToken() (token string, err error) {
	isExpired, err := s.isJWTExpired(s.getRenkuAccessToken())
	if err != nil {
		return "", err
	}
	if isExpired {
		if err = s.refreshRenkuAccessToken(); err != nil {
			return "", err
		}
	}
	return s.getRenkuAccessToken(), nil
}

func (s *TokenStore) getRenkuAccessToken() string {
	s.renkuAccessTokenLock.RLock()
	defer s.renkuAccessTokenLock.RUnlock()
	return s.renkuAccessToken
}

type renkuTokenRefreshResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
}

// Refreshes the renku access token.
func (s *TokenStore) refreshRenkuAccessToken() error {
	s.renkuAccessTokenLock.Lock()
	defer s.renkuAccessTokenLock.Unlock()
	payload := url.Values{}
	payload.Add("grant_type", "refresh_token")
	payload.Add("refresh_token", s.renkuRefreshToken)
	body := strings.NewReader(payload.Encode())
	req, err := http.NewRequest(http.MethodPost, s.Config.RenkuURL.JoinPath(fmt.Sprintf("auth/realms/%s/protocol/openid-connect/token", s.Config.RenkuRealm)).String(), body)
	if err != nil {
		return err
	}
	req.SetBasicAuth(s.Config.RenkuClientID, string(s.Config.RenkuClientSecret))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	if res.StatusCode != 200 {
		err = fmt.Errorf("cannot refresh renku access token, failed with staus code: %d", res.StatusCode)
		return err
	}
	var resParsed renkuTokenRefreshResponse
	err = json.NewDecoder(res.Body).Decode(&resParsed)
	if err != nil {
		return err
	}
	s.renkuAccessToken = resParsed.AccessToken
	if resParsed.RefreshToken != "" {
		s.renkuRefreshToken = resParsed.RefreshToken
	}
	return nil
}

// Checks if the expiry of the token has passed or is coming up soon based on a predefined threshold.
// NOTE: no signature validation is performed at all. All of the tokens in the proxy are trusted implicitly
// because they come from trusted/controlled sources.
func (s *TokenStore) isJWTExpired(token string) (isExpired bool, err error) {
	parser := jwt.NewParser()
	claims := jwt.RegisteredClaims{}
	if _, _, err := parser.ParseUnverified(token, &claims); err != nil {
		// log.Printf("Cannot parse token claims, assuming token is expired: %s\n", err.Error())
		return true, err
	}
	expiresAt, err := claims.GetExpirationTime()
	if err != nil {
		return true, err
	}
	// `exp` claim is not set -> the token does not expire
	if expiresAt == nil {
		return false, nil
	}
	now := time.Now()
	valid := now.Before(expiresAt.Time)
	return !valid, nil

	// // VerifyExpiresAt returns cmp.Before(exp) if exp is set, otherwise !req if exp is not set.
	// // Here we have it setup so that if the exp claim is not defined we assume the token is not expired.
	// // Keycloak does not set the `exp` claim on tokens that have the offline access grant - because they do not expire.
	// jwtIsNotExpired := claims.VerifyExpiresAt(time.Now().Add(s.ExpirationLeeway), false)
	// return !jwtIsNotExpired, nil
}
