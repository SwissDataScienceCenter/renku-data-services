/*
 * Renku data services
 * Services that provide information about data, users and compute resources. All errors have the same format as the schema called ErrorResponse.
 *
 * OpenAPI spec version: v1
 *
 * NOTE: This class is auto generated by OpenAPI Generator.
 * https://github.com/OpenAPITools/openapi-generator
 *
 * OpenAPI generator version: 6.6.0-SNAPSHOT
 */

import http from "k6/http";
import { group, check, sleep } from "k6";
import {
  randomString,
  randomIntBetween,
} from "https://jslib.k6.io/k6-utils/1.2.0/index.js";

const BASE_URL = "http://localhost:8000/api/data";
// Sleep duration between successive requests.
// You might want to edit the value of this variable or remove calls to the sleep function on the script.
const SLEEP_DURATION = 0.1;
// Global variables should be initialized.

export const options = {
  scenarios: {
    lecture: {
      executor: "per-vu-iterations",
      vus: 10,
      iterations: 10,
    },
  },
};

export default function () {
  group("/error", () => {
    // Request No. 1:
    {
      let url = BASE_URL + `/error`;
      let request = http.get(url);
    }
  });

  group("/resource_pools/", () => {
    {
      let url = BASE_URL + `/resource_pools`;
      let name = randomString(10);
      // TODO: edit the parameters of the request body.
      let body = {
        quota: {
          cpu: randomIntBetween(10, 50) / 10,
          memory: randomIntBetween(10000, 100000),
          gpu: randomIntBetween(1, 4),
          storage: randomIntBetween(10000, 100000),
        },
        classes: [
          {
            name: "class1",
            cpu: randomIntBetween(1, 10) / 10,
            memory: randomIntBetween(1000, 10000),
            gpu: 1,
            storage: randomIntBetween(1000, 10000),
          },
        ],
        name: name,
      };
      let params = {
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        tags: { type: "post" },
      };
      let response = http.post(url, JSON.stringify(body), params);

      check(response, {
        "The resource pool was created": (r) => r.status === 201,
      });

      let created_pool = JSON.parse(response.body);
      let resource_pool_id = created_pool.id;
      sleep(SLEEP_DURATION);

      url = BASE_URL + `/resource_pools/${resource_pool_id}`;
      response = http.get(url, { tags: { type: "get_by_id" } });

      check(response, {
        "The get resource pool definition": (r) => r.status === 200,
      });

      sleep(SLEEP_DURATION);

      url = BASE_URL + `/resource_pools?name=${name}`;
      response = http.get(url, { tags: { type: "get_by_name" } });

      let passed = check(response, {
        "The get by name resource pool definitions": (r) => r.status === 200,
      });

      if (!passed) {
        console.log(
          `Request error ${response.status}, ${url}: ${response.body}`
        );
      }

      sleep(SLEEP_DURATION);

      url = BASE_URL + `/resource_pools/${resource_pool_id}`;
      response = http.del(url, {}, { tags: { type: "delete" } });

      check(response, {
        "The delete resource pool definitions": (r) => r.status === 204,
      });
    }
  });

  group("/version", () => {
    // Request No. 1:
    {
      let url = BASE_URL + `/version`;
      let request = http.get(url);

      check(request, {
        "The error": (r) => r.status === 200,
      });
    }
  });
}
