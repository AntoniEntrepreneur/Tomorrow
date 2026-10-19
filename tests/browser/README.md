# Construction page browser tests

Install the JavaScript test dependency and Chromium once, then run the browser suite:

```sh
npm install
npx playwright install chromium
npm run test:browser
```

The suite serves the production page and JavaScript modules, drives them in Chromium,
and stubs only the HTTP endpoints so it can assert the requests made by visible actions.
