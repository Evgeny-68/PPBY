"""Проверки двух курсов без интернета и без открытия окон."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

import requests

spec = importlib.util.spec_from_file_location(
    'currency_app', Path(__file__).with_name('Задание 5.py')
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def response_with(rate, target='RUB'):
    response = Mock()
    response.json.return_value = {
        'result': 'success', 'rates': {target: rate}
    }
    return response


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        for name, code in (
            ('base_combobox', 'EUR'),
            ('second_base_combobox', 'USD'),
            ('target_combobox', 'RUB'),
        ):
            patcher = patch.object(app, name, Mock(), create=True)
            widget = patcher.start()
            widget.get.return_value = code
            self.addCleanup(patcher.stop)

        get_patcher = patch.object(app.requests, 'get')
        self.get = get_patcher.start()
        self.addCleanup(get_patcher.stop)
        messages_patcher = patch.object(app, 'mb')
        self.messages = messages_patcher.start()
        self.addCleanup(messages_patcher.stop)

    def test_both_json_rates_are_shown_together(self):
        responses = [response_with(101.25), response_with(93.5)]
        self.get.side_effect = responses
        app.exchange()
        self.assertEqual(self.get.call_args_list, [
            call('https://open.er-api.com/v6/latest/EUR', timeout=10),
            call('https://open.er-api.com/v6/latest/USD', timeout=10),
        ])
        for response in responses:
            response.raise_for_status.assert_called_once()
            response.json.assert_called_once()
        self.messages.showinfo.assert_called_once_with(
            'Курсы обмена', '1 EUR = 101.25 RUB\n1 USD = 93.5 RUB'
        )
        self.messages.showerror.assert_not_called()

    def test_small_rate_does_not_become_zero(self):
        app.target_combobox.get.return_value = 'GBP'
        self.get.side_effect = [
            response_with(0.000061, 'GBP'), response_with(0.75, 'GBP')
        ]
        app.exchange()
        self.assertIn('6.1e-05 GBP', self.messages.showinfo.call_args.args[1])

    def test_base_can_equal_target(self):
        app.target_combobox.get.return_value = 'EUR'
        self.get.side_effect = [
            response_with(1, 'EUR'), response_with(0.92, 'EUR')
        ]
        app.exchange()
        self.assertIn('1 EUR = 1 EUR', self.messages.showinfo.call_args.args[1])

    def test_identical_bases_still_produce_two_lines(self):
        app.second_base_combobox.get.return_value = 'EUR'
        self.get.return_value = response_with(101.25)
        app.exchange()
        self.assertEqual(
            self.messages.showinfo.call_args.args[1].splitlines(),
            ['1 EUR = 101.25 RUB', '1 EUR = 101.25 RUB']
        )

    def test_missing_selection_does_not_send_requests(self):
        app.second_base_combobox.get.return_value = ''
        app.exchange()
        self.get.assert_not_called()
        self.messages.showwarning.assert_called_once()

    def test_first_failure_does_not_prevent_second_rate(self):
        self.get.side_effect = [requests.Timeout(), response_with(93.5)]
        app.exchange()
        message = self.messages.showwarning.call_args.args[1]
        self.assertIn('EUR: не удалось', message)
        self.assertIn('1 USD = 93.5 RUB', message)
        self.messages.showinfo.assert_not_called()

    def test_second_failure_keeps_first_rate(self):
        self.get.side_effect = [response_with(101.25), requests.Timeout()]
        app.exchange()
        message = self.messages.showwarning.call_args.args[1]
        self.assertIn('1 EUR = 101.25 RUB', message)
        self.assertIn('USD: не удалось', message)

    def test_both_http_failures_show_one_error(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError('503')
        self.get.return_value = response
        app.exchange()
        self.messages.showerror.assert_called_once()
        self.assertEqual(self.get.call_count, 2)
        response.json.assert_not_called()

    def test_invalid_json_is_reported(self):
        invalid = Mock()
        invalid.json.side_effect = requests.exceptions.JSONDecodeError(
            'Invalid JSON', '<html>', 0
        )
        self.get.side_effect = [invalid, response_with(93.5)]
        app.exchange()
        self.assertIn(
            'некорректный JSON', self.messages.showwarning.call_args.args[1]
        )

    def test_api_and_data_errors_are_reported(self):
        payloads = [
            {'result': 'error', 'error-type': 'unsupported-code'},
            {'result': 'success', 'rates': {}},
            {'result': 'success'},
            {'result': 'success', 'rates': None},
            {'result': 'success', 'rates': {'RUB': float('nan')}},
            {'result': 'success', 'rates': {'RUB': -1}},
            None,
            [],
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.messages.reset_mock()
                invalid = Mock()
                invalid.json.return_value = payload
                self.get.side_effect = [invalid, response_with(93.5)]
                app.exchange()
                self.messages.showwarning.assert_called_once()
                self.assertIn(
                    '1 USD = 93.5 RUB',
                    self.messages.showwarning.call_args.args[1]
                )


if __name__ == '__main__':
    unittest.main()
