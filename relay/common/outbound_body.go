package common

import (
	"bytes"
	"io"
	"net/http"

	rootcommon "github.com/QuantumNous/new-api/common"
)

type RequestBodyReplayer interface {
	NewRequestBody() (io.ReadCloser, error)
}

type replayableBody struct{ storage rootcommon.BodyStorage }

func (body *replayableBody) Read(buffer []byte) (int, error) { return body.storage.Read(buffer) }

func (body *replayableBody) NewRequestBody() (io.ReadCloser, error) {
	data, err := body.storage.Bytes()
	if err != nil {
		return nil, err
	}
	return io.NopCloser(bytes.NewReader(data)), nil
}

// AttachRequestBodyReplay configures req.GetBody when body knows how to rewind
// itself. Existing net/http GetBody implementations are preserved.
func AttachRequestBodyReplay(req *http.Request, body io.Reader) {
	if req == nil || req.GetBody != nil {
		return
	}
	if body == nil {
		req.GetBody = func() (io.ReadCloser, error) { return http.NoBody, nil }
		return
	}
	replayer, ok := body.(RequestBodyReplayer)
	if !ok {
		return
	}
	req.GetBody = replayer.NewRequestBody
}

// NewOutboundJSONBody wraps the already-marshaled upstream request body into a
// BodyStorage. The caller must close the returned closer after the upstream call.
func NewOutboundJSONBody(data []byte) (body io.Reader, size int64, closer io.Closer, err error) {
	storage, err := rootcommon.CreateBodyStorage(data)
	if err != nil {
		return nil, 0, nil, err
	}
	return &replayableBody{storage: storage}, storage.Size(), storage, nil
}
